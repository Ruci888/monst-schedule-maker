"""モンストアプリの画面録画から降臨候補を抽出する。

動画と抽出フレームは一時ディレクトリだけで扱い、処理終了時に削除する。
OCR結果は必ず管理画面の承認待ち候補として返し、自動公開しない。
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path


MAX_VIDEO_BYTES = 100 * 1024 * 1024
MAX_VIDEO_SECONDS = 180
FRAME_INTERVAL_SECONDS = 1.0
MAX_SAMPLE_FRAMES = 180

DIFFICULTY_PATTERNS = (
    ("超究極・兵", re.compile(r"超究極\s*[・･]\s*兵")),
    ("超究極", re.compile(r"超究極")),
    ("黎絶", re.compile(r"黎絶")),
    ("轟絶", re.compile(r"轟絶")),
    ("爆絶", re.compile(r"爆絶")),
    ("超絶", re.compile(r"超絶")),
    ("激究極", re.compile(r"激究極")),
    ("星5制限", re.compile(r"星\s*5\s*制限")),
    ("究極", re.compile(r"究極")),
    ("極", re.compile(r"(?<!究)極")),
)

DATE_TIME_PATTERN = re.compile(
    r"(?P<start_month>\d{1,2})\s*/\s*(?P<start_day>\d{1,2})"
    r"(?:\s*[（(][^）)]*[）)])?\s*"
    r"(?P<start_hour>\d{1,2})\s*:\s*(?P<start_minute>\d{2})\s*"
    r"[~〜～ー―-]+\s*"
    r"(?P<end_month>\d{1,2})\s*/\s*(?P<end_day>\d{1,2})"
    r"(?:\s*[（(][^）)]*[）)])?\s*"
    r"(?P<end_hour>\d{1,2})\s*:\s*(?P<end_minute>\d{2})"
)

IGNORED_NAME_WORDS = (
    "CLEAR",
    "適正度",
    "難易度",
    "種類以上",
    "クリア",
    "予約",
    "最大",
    "スケジュール",
    "繰り返し予約",
)


class VideoScheduleError(RuntimeError):
    """管理画面にそのまま表示できる動画処理エラー。"""


@dataclass
class VideoExtractionResult:
    candidates: list[dict]
    recognized_count: int
    published_duplicate_count: int
    pending_duplicate_count: int
    video_duplicate_count: int
    ocr_error_count: int
    sampled_frame_count: int
    video_fingerprint: str

    def as_dict(self):
        return {
            "candidates": self.candidates,
            "recognized_count": self.recognized_count,
            "published_duplicate_count": self.published_duplicate_count,
            "pending_duplicate_count": self.pending_duplicate_count,
            "video_duplicate_count": self.video_duplicate_count,
            "ocr_error_count": self.ocr_error_count,
            "sampled_frame_count": self.sampled_frame_count,
            "video_fingerprint": self.video_fingerprint,
        }


def normalize_ocr_text(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    replacements = {
        "：": ":",
        "／": "/",
        "〜": "～",
        "~": "～",
        "―": "～",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"[ \t]+", " ", text).strip()


def normalize_identity_name(value):
    text = normalize_ocr_text(value).lower()
    return re.sub(r"[\s・･\-ー_!！?？'\"「」『』()（）]", "", text)


def schedule_identity(schedule):
    return (
        int(schedule.get("year", 0)),
        str(schedule.get("date", "")),
        str(schedule.get("start_time", "")),
        normalize_identity_name(schedule.get("name", "")),
        str(schedule.get("difficulty", "")),
    )


def find_difficulty(text):
    normalized = normalize_ocr_text(text)
    for difficulty, pattern in DIFFICULTY_PATTERNS:
        if pattern.search(normalized):
            return difficulty
    return ""


def find_date_time(text):
    normalized = normalize_ocr_text(text)
    match = DATE_TIME_PATTERN.search(normalized)
    if not match:
        return None
    values = {key: int(value) for key, value in match.groupdict().items()}
    if not (
        1 <= values["start_month"] <= 12
        and 1 <= values["end_month"] <= 12
        and 1 <= values["start_day"] <= 31
        and 1 <= values["end_day"] <= 31
        and 0 <= values["start_hour"] <= 23
        and 0 <= values["end_hour"] <= 23
        and 0 <= values["start_minute"] <= 59
        and 0 <= values["end_minute"] <= 59
    ):
        return None
    return {
        "date": f"{values['start_month']}/{values['start_day']}",
        "start_time": f"{values['start_hour']:02d}:{values['start_minute']:02d}",
        "end_time": f"{values['end_hour']:02d}:{values['end_minute']:02d}",
    }


def _clean_name_line(line):
    text = normalize_ocr_text(line)
    text = re.sub(r"^[^\wぁ-んァ-ヶ一-龠々]+", "", text)
    text = re.sub(r"[^\wぁ-んァ-ヶ一-龠々・･\-ー\s]+$", "", text)
    return text.strip()


def find_character_name(text):
    candidates = []
    for raw_line in str(text or "").splitlines():
        line = _clean_name_line(raw_line)
        if len(normalize_identity_name(line)) < 2:
            continue
        if DATE_TIME_PATTERN.search(normalize_ocr_text(line)):
            continue
        if any(word.lower() in line.lower() for word in IGNORED_NAME_WORDS):
            continue
        if find_difficulty(line) and len(line) <= 10:
            continue
        if re.fullmatch(r"[\d/:～~\-()（）月火水木金土日]+", line):
            continue
        # 名前はカード内の日時・条件説明より下にあるため、後の行を優先する。
        candidates.append(line)
    return candidates[-1] if candidates else ""


def candidate_from_card_text(text, year, attribute="", confidence=0.0):
    date_time = find_date_time(text)
    difficulty = find_difficulty(text)
    name = find_character_name(text)
    if not date_time or not difficulty or not name:
        return None
    return {
        "year": int(year),
        **date_time,
        "name": name,
        "quest_name": "",
        "attribute": attribute,
        "difficulty": difficulty,
        "category": "high_difficulty",
        "group_name": "",
        "availability_type": "時間指定",
        "period_end_date": "",
        "source_type": "game",
        "source_url": "",
        "review_reason": (
            "アプリ画面録画から文字認識しました。"
            "キャラ名・属性・難易度・日時を確認してください。"
        ),
        "ocr_confidence": round(float(confidence), 1),
        "confirmed_at": "",
        "published": False,
    }


def _similar_candidate(left, right):
    if (
        int(left.get("year", 0)) != int(right.get("year", 0))
        or left.get("date") != right.get("date")
        or left.get("start_time") != right.get("start_time")
        or left.get("difficulty") != right.get("difficulty")
    ):
        return False
    left_name = normalize_identity_name(left.get("name"))
    right_name = normalize_identity_name(right.get("name"))
    return SequenceMatcher(None, left_name, right_name).ratio() >= 0.92


def deduplicate_video_candidates(candidates):
    unique = []
    duplicate_count = 0
    for candidate in candidates:
        matching_index = next(
            (
                index
                for index, current in enumerate(unique)
                if _similar_candidate(current, candidate)
            ),
            None,
        )
        if matching_index is None:
            unique.append(candidate)
            continue
        duplicate_count += 1
        if candidate.get("ocr_confidence", 0) > unique[matching_index].get(
            "ocr_confidence", 0
        ):
            unique[matching_index] = candidate
    return unique, duplicate_count


def filter_existing_candidates(candidates, published, pending):
    published_keys = {schedule_identity(item) for item in published}
    pending_keys = {schedule_identity(item) for item in pending}
    new_candidates = []
    published_duplicates = 0
    pending_duplicates = 0
    for candidate in candidates:
        identity = schedule_identity(candidate)
        if identity in published_keys:
            published_duplicates += 1
        elif identity in pending_keys:
            pending_duplicates += 1
        else:
            new_candidates.append(candidate)
    return new_candidates, published_duplicates, pending_duplicates


def _validate_video(video_bytes):
    if not video_bytes:
        raise VideoScheduleError("動画ファイルが空です。")
    if len(video_bytes) > MAX_VIDEO_BYTES:
        raise VideoScheduleError("動画は100MB以下にしてください。")
    if b"ftyp" not in video_bytes[:64]:
        raise VideoScheduleError("MP4またはMOV形式の動画を選択してください。")


def _require_video_dependencies():
    try:
        import cv2
        import pytesseract
    except ImportError as error:
        raise VideoScheduleError(
            "動画OCR用ライブラリが未導入です。requirements.txtとpackages.txtを反映してください。"
        ) from error
    if not shutil.which("tesseract"):
        raise VideoScheduleError(
            "文字認識エンジンTesseractが見つかりません。packages.txtを反映してください。"
        )
    languages = set(pytesseract.get_languages(config=""))
    if "jpn" not in languages:
        raise VideoScheduleError(
            "日本語OCRデータがありません。packages.txtのtesseract-ocr-jpnを確認してください。"
        )
    return cv2, pytesseract


def _frame_hash(cv2, frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (9, 8))
    differences = resized[:, 1:] > resized[:, :-1]
    return sum(int(value) << index for index, value in enumerate(differences.flat))


def _hamming_distance(left, right):
    return (left ^ right).bit_count()


def _prepare_ocr_image(cv2, image):
    enlarged = cv2.resize(image, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if binary.mean() < 127:
        binary = cv2.bitwise_not(binary)
    return binary


def _group_ocr_lines(data):
    grouped = {}
    count = len(data.get("text", []))
    for index in range(count):
        word = normalize_ocr_text(data["text"][index])
        if not word:
            continue
        key = (
            data["block_num"][index],
            data["par_num"][index],
            data["line_num"][index],
        )
        item = grouped.setdefault(key, {"words": [], "top": 10**9, "confidence": []})
        item["words"].append(word)
        item["top"] = min(item["top"], int(data["top"][index]))
        try:
            confidence = float(data["conf"][index])
            if confidence >= 0:
                item["confidence"].append(confidence)
        except (TypeError, ValueError):
            pass
    results = []
    for item in grouped.values():
        results.append({
            "text": " ".join(item["words"]),
            "top": item["top"],
            "confidence": (
                sum(item["confidence"]) / len(item["confidence"])
                if item["confidence"]
                else 0.0
            ),
        })
    return sorted(results, key=lambda item: item["top"])


def _infer_attribute(cv2, card):
    height, width = card.shape[:2]
    # 左端の赤いドクロ・黄色い宝箱と右端の予約ボタンを除き、
    # 属性色で描かれたキャラ名の領域だけを見る。
    region = card[
        int(height * 0.52): int(height * 0.92),
        int(width * 0.20): int(width * 0.66),
    ]
    if region.size == 0:
        return ""
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 1] >= 90) & (hsv[:, :, 2] >= 100)
    hues = hsv[:, :, 0][mask]
    if hues.size < 10:
        return ""
    counts = {
        "火": int(((hues < 12) | (hues >= 170)).sum()),
        "光": int(((hues >= 12) & (hues < 35)).sum()),
        "木": int(((hues >= 35) & (hues < 88)).sum()),
        "水": int(((hues >= 88) & (hues < 122)).sum()),
        "闇": int(((hues >= 122) & (hues < 170)).sum()),
    }
    attribute, count = max(counts.items(), key=lambda item: item[1])
    return attribute if count >= 8 else ""


def _extract_from_frame(cv2, pytesseract, frame, year):
    height, width = frame.shape[:2]
    # 上部のユーザー名・ランクと下部メニューをOCR対象から除外する。
    crop_top = int(height * 0.34)
    crop_bottom = int(height * 0.91)
    content = frame[crop_top:crop_bottom, :]
    prepared = _prepare_ocr_image(cv2, content)
    data = pytesseract.image_to_data(
        prepared,
        lang="jpn+eng",
        config="--psm 6",
        output_type=pytesseract.Output.DICT,
    )
    lines = _group_ocr_lines(data)
    date_lines = [line for line in lines if find_date_time(line["text"])]
    candidates = []
    failed_count = 0
    scale = prepared.shape[0] / content.shape[0]
    for line in date_lines:
        original_top = max(0, int(line["top"] / scale) - 8)
        card_bottom = min(content.shape[0], original_top + int(height * 0.115))
        card = content[original_top:card_bottom, : int(width * 0.78)]
        if card.size == 0:
            failed_count += 1
            continue
        card_text = pytesseract.image_to_string(
            _prepare_ocr_image(cv2, card),
            lang="jpn+eng",
            config="--psm 6",
        )
        # 日時行がカード再OCRで欠けた場合に、先に検出した行を補う。
        combined_text = f"{line['text']}\n{card_text}"
        candidate = candidate_from_card_text(
            combined_text,
            year,
            attribute=_infer_attribute(cv2, card),
            confidence=line["confidence"],
        )
        if candidate:
            candidates.append(candidate)
        else:
            failed_count += 1
    return candidates, failed_count


def extract_video_schedule_candidates(
    video_bytes,
    year,
    published_schedules=None,
    pending_candidates=None,
):
    """動画を解析し、既存データと重複しない承認待ち候補を返す。"""
    _validate_video(video_bytes)
    try:
        year = int(year)
    except (TypeError, ValueError) as error:
        raise VideoScheduleError("年は4桁の数字で指定してください。") from error
    if not 2020 <= year <= 2100:
        raise VideoScheduleError("年は2020～2100の範囲で指定してください。")

    cv2, pytesseract = _require_video_dependencies()
    fingerprint = hashlib.sha256(video_bytes).hexdigest()
    all_candidates = []
    ocr_error_count = 0
    sampled_frame_count = 0

    with tempfile.TemporaryDirectory(prefix="monst_video_") as temporary_directory:
        video_path = Path(temporary_directory) / "upload.mp4"
        video_path.write_bytes(video_bytes)
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise VideoScheduleError("動画を開けませんでした。MP4またはMOVで撮り直してください。")
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
            frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if fps <= 0:
                raise VideoScheduleError("動画のフレームレートを取得できませんでした。")
            duration = frame_count / fps if frame_count else 0
            if duration > MAX_VIDEO_SECONDS:
                raise VideoScheduleError("動画は3分以内にしてください。")
            step = max(1, int(round(fps * FRAME_INTERVAL_SECONDS)))
            frame_index = 0
            previous_hash = None
            while sampled_frame_count < MAX_SAMPLE_FRAMES:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame_index % step:
                    frame_index += 1
                    continue
                frame_index += 1
                current_hash = _frame_hash(cv2, frame)
                if previous_hash is not None and _hamming_distance(
                    previous_hash, current_hash
                ) <= 3:
                    continue
                previous_hash = current_hash
                sampled_frame_count += 1
                candidates, failed = _extract_from_frame(
                    cv2, pytesseract, frame, year
                )
                all_candidates.extend(candidates)
                ocr_error_count += failed
        finally:
            capture.release()

    unique_candidates, video_duplicate_count = deduplicate_video_candidates(
        all_candidates
    )
    for candidate in unique_candidates:
        candidate["video_fingerprint"] = fingerprint
        candidate["fetched_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
    new_candidates, published_duplicates, pending_duplicates = (
        filter_existing_candidates(
            unique_candidates,
            published_schedules or [],
            pending_candidates or [],
        )
    )
    return VideoExtractionResult(
        candidates=new_candidates,
        recognized_count=len(unique_candidates),
        published_duplicate_count=published_duplicates,
        pending_duplicate_count=pending_duplicates,
        video_duplicate_count=video_duplicate_count,
        ocr_error_count=ocr_error_count,
        sampled_frame_count=sampled_frame_count,
        video_fingerprint=fingerprint,
    )

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
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path


MAX_VIDEO_BYTES = 100 * 1024 * 1024
MAX_VIDEO_SECONDS = 180
FRAME_INTERVAL_SECONDS = 0.5
MAX_SAMPLE_FRAMES = 360

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
JAPANESE_PATTERN = re.compile(r"[ぁ-んァ-ヶー一-龠々〆ヵヶ]")
JAPANESE_NAME_PATTERN = re.compile(
    r"[ぁ-んァ-ヶー一-龠々〆ヵヶ]+"
    r"(?:[・･\s]+[ぁ-んァ-ヶー一-龠々〆ヵヶ]+)*"
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


def candidate_identity(schedule):
    """未入力候補同士が同一扱いにならない承認待ち用の識別子。"""
    complete = all(
        schedule.get(field)
        for field in ("name", "difficulty")
    )
    if not complete and schedule.get("candidate_id"):
        return ("candidate", str(schedule["candidate_id"]))
    return ("schedule", *schedule_identity(schedule))


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


def japanese_ratio(text):
    compact = re.sub(r"[\s・･\-ー]", "", normalize_ocr_text(text))
    if not compact:
        return 0.0
    return len(JAPANESE_PATTERN.findall(compact)) / len(compact)


def clean_ocr_character_name(text):
    """OCR文字列から英数字やUI断片を除き、日本語の名前部分だけを返す。"""
    normalized = normalize_ocr_text(text)
    matches = [match.group(0).strip() for match in JAPANESE_NAME_PATTERN.finditer(normalized)]
    matches = [
        match
        for match in matches
        if len(normalize_identity_name(match)) >= 2
        and not any(word in match for word in IGNORED_NAME_WORDS)
        and not find_difficulty(match)
    ]
    if not matches:
        return ""
    best = max(matches, key=lambda value: len(normalize_identity_name(value)))
    parts = best.split()
    # 「w 竜 オーポレン BRE」のような1文字の誤認識を名前の前から除く。
    if len(parts) >= 2 and len(parts[0]) == 1 and len("".join(parts[1:])) >= 3:
        best = " ".join(parts[1:])
    return best.strip()


def is_plausible_character_name(value):
    name = clean_ocr_character_name(value)
    length = len(normalize_identity_name(name))
    return bool(name) and 2 <= length <= 30 and japanese_ratio(name) >= 0.75


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


def candidate_from_card_text(
    text,
    year,
    attribute="",
    confidence=0.0,
    recognized_name=None,
    raw_name_text="",
    ocr_status="",
    recognized_difficulty=None,
    raw_difficulty_text="",
    visual_signature="",
):
    date_time = find_date_time(text)
    difficulty = (
        find_difficulty(recognized_difficulty)
        if recognized_difficulty is not None
        else find_difficulty(text)
    )
    name = (
        clean_ocr_character_name(recognized_name)
        if recognized_name is not None
        else clean_ocr_character_name(find_character_name(text))
    )
    if not date_time:
        return None

    missing_fields = []
    if not name:
        missing_fields.append("名前要入力")
    if not attribute:
        missing_fields.append("属性要確認")
    if not difficulty:
        missing_fields.append("難易度要確認")
    status_parts = ["要目視確認"]
    status_parts.extend(missing_fields)
    if ocr_status and ocr_status not in status_parts:
        status_parts.append(ocr_status)

    identity_source = "|".join([
        str(year),
        date_time["date"],
        date_time["start_time"],
        normalize_identity_name(name),
        visual_signature or normalize_ocr_text(raw_name_text),
    ])
    candidate = {
        "candidate_id": hashlib.sha1(
            identity_source.encode("utf-8")
        ).hexdigest()[:20],
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
        "ocr_raw_name": normalize_ocr_text(raw_name_text),
        "ocr_raw_difficulty": normalize_ocr_text(raw_difficulty_text),
        "ocr_status": "・".join(status_parts),
        "ocr_votes": 1,
        "visual_signature": visual_signature,
        "confirmed_at": "",
        "published": False,
    }
    return candidate


def _similar_candidate(left, right):
    if (
        int(left.get("year", 0)) != int(right.get("year", 0))
        or left.get("date") != right.get("date")
        or left.get("start_time") != right.get("start_time")
    ):
        return False
    left_signature = str(left.get("visual_signature", ""))
    right_signature = str(right.get("visual_signature", ""))
    if left_signature and right_signature:
        try:
            distance = (
                int(left_signature, 16) ^ int(right_signature, 16)
            ).bit_count()
            if distance <= 16:
                return True
        except ValueError:
            if left_signature == right_signature:
                return True

    left_name = normalize_identity_name(left.get("name"))
    right_name = normalize_identity_name(right.get("name"))
    if not left_name or not right_name:
        return False
    if (
        left.get("difficulty")
        and right.get("difficulty")
        and left.get("difficulty") != right.get("difficulty")
    ):
        return False
    return SequenceMatcher(None, left_name, right_name).ratio() >= 0.82


def _consensus_exact_value(candidates, field):
    values = [str(item.get(field, "")).strip() for item in candidates]
    values = [value for value in values if value]
    if not values:
        return ""
    ranked = Counter(values).most_common()
    if len(ranked) >= 2 and ranked[0][1] == ranked[1][1]:
        return ""
    return ranked[0][0]


def _consensus_name(candidates):
    groups = []
    for candidate in candidates:
        name = clean_ocr_character_name(candidate.get("name", ""))
        normalized = normalize_identity_name(name)
        if not normalized:
            continue
        matching_group = next(
            (
                group
                for group in groups
                if SequenceMatcher(
                    None,
                    normalized,
                    group["normalized"],
                ).ratio() >= 0.82
            ),
            None,
        )
        if matching_group is None:
            matching_group = {
                "normalized": normalized,
                "items": [],
            }
            groups.append(matching_group)
        matching_group["items"].append(candidate)
    if not groups:
        return ""

    selected_group = max(
        groups,
        key=lambda group: (
            len(group["items"]),
            sum(
                float(item.get("ocr_confidence", 0) or 0)
                for item in group["items"]
            ),
        ),
    )
    selected = max(
        selected_group["items"],
        key=lambda item: float(item.get("ocr_confidence", 0) or 0),
    )
    return clean_ocr_character_name(selected.get("name", ""))


def _join_ocr_values(candidates, field):
    values = []
    for candidate in candidates:
        value = normalize_ocr_text(candidate.get(field, ""))
        if value and value not in values:
            values.append(value)
    return " / ".join(values)[:1000]


def candidate_review_status(candidate):
    parts = ["要目視確認"]
    field_labels = (
        ("name", "名前要入力"),
        ("attribute", "属性要確認"),
        ("difficulty", "難易度要確認"),
    )
    parts.extend(
        label
        for field, label in field_labels
        if not candidate.get(field)
    )
    return "・".join(parts)


def deduplicate_video_candidates(candidates):
    groups = []
    for candidate in candidates:
        matching_group = next(
            (
                group
                for group in groups
                if any(
                    _similar_candidate(current, candidate)
                    for current in group
                )
            ),
            None,
        )
        if matching_group is None:
            groups.append([candidate])
        else:
            matching_group.append(candidate)

    unique = []
    for group in groups:
        selected = dict(max(
            group,
            key=lambda item: float(item.get("ocr_confidence", 0) or 0),
        ))
        selected["name"] = _consensus_name(group)
        selected["attribute"] = _consensus_exact_value(group, "attribute")
        selected["difficulty"] = _consensus_exact_value(group, "difficulty")
        selected["ocr_raw_name"] = _join_ocr_values(group, "ocr_raw_name")
        selected["ocr_raw_difficulty"] = _join_ocr_values(
            group, "ocr_raw_difficulty"
        )
        selected["ocr_raw_date"] = _join_ocr_values(group, "ocr_raw_date")
        selected["ocr_votes"] = sum(
            int(item.get("ocr_votes", 1) or 1)
            for item in group
        )
        selected["ocr_status"] = candidate_review_status(selected)
        unique.append(selected)

    duplicate_count = len(candidates) - len(unique)
    return unique, duplicate_count


def filter_existing_candidates(candidates, published, pending):
    published_keys = {schedule_identity(item) for item in published}
    new_candidates = []
    published_duplicates = 0
    pending_duplicates = 0
    for candidate in candidates:
        identity = schedule_identity(candidate)
        complete_identity = all(
            candidate.get(field)
            for field in ("name", "difficulty")
        )
        if complete_identity and identity in published_keys:
            published_duplicates += 1
        elif any(
            candidate_identity(candidate) == candidate_identity(item)
            or _similar_candidate(candidate, item)
            for item in pending
        ):
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
    resized = cv2.resize(gray, (17, 16))
    differences = resized[:, 1:] > resized[:, :-1]
    return sum(int(value) << index for index, value in enumerate(differences.flat))


def _frame_sharpness(cv2, frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _detect_game_viewport(cv2, frame):
    """録画の黒い余白を除き、実際にゲームが表示されている領域を返す。"""
    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    active = gray >= 12

    active_columns = active.sum(axis=0)
    active_rows = active.sum(axis=1)
    minimum_column_pixels = max(4, int(height * 0.025))
    minimum_row_pixels = max(4, int(width * 0.025))

    columns = [
        index
        for index, count in enumerate(active_columns)
        if int(count) >= minimum_column_pixels
    ]
    rows = [
        index
        for index, count in enumerate(active_rows)
        if int(count) >= minimum_row_pixels
    ]
    if not columns or not rows:
        return frame

    left = max(0, columns[0] - 2)
    right = min(width, columns[-1] + 3)
    top = max(0, rows[0] - 2)
    bottom = min(height, rows[-1] + 3)

    # 一時的な暗転画面などを誤って極端に小さく切り出さない。
    if (
        right - left < int(width * 0.55)
        or bottom - top < int(height * 0.55)
    ):
        return frame
    return frame[top:bottom, left:right]


def _image_signature(cv2, image):
    if image.size == 0:
        return ""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (17, 16))
    differences = resized[:, 1:] > resized[:, :-1]
    value = sum(
        int(bit) << index
        for index, bit in enumerate(differences.flat)
    )
    return f"{value:064x}"


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


def _enlarge_name_image(cv2, image):
    return cv2.resize(
        image,
        None,
        fx=4.0,
        fy=4.0,
        interpolation=cv2.INTER_CUBIC,
    )


def _name_color_mask(cv2, image, attribute=""):
    """暗い背景を消し、属性色のキャラ名を黒文字・白背景にする。"""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    ranges = {
        "火": ((0, 12), (170, 179)),
        "光": ((12, 35),),
        "木": ((35, 88),),
        "水": ((88, 122),),
        "闇": ((122, 170),),
    }
    selected_ranges = ranges.get(attribute, ((0, 179),))
    mask = None
    for minimum_hue, maximum_hue in selected_ranges:
        current = cv2.inRange(
            hsv,
            (minimum_hue, 65, 75),
            (maximum_hue, 255, 255),
        )
        mask = current if mask is None else cv2.bitwise_or(mask, current)
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
    )
    # Tesseractが読みやすい白背景・黒文字へ変換する。
    return cv2.bitwise_not(mask)


def _ocr_name_variant(pytesseract, image):
    data = pytesseract.image_to_data(
        image,
        lang="jpn+eng",
        config="--psm 7 -c preserve_interword_spaces=1",
        output_type=pytesseract.Output.DICT,
    )
    words = []
    confidences = []
    for text, confidence in zip(data.get("text", []), data.get("conf", [])):
        text = normalize_ocr_text(text)
        if not text:
            continue
        words.append(text)
        try:
            value = float(confidence)
            if value >= 0:
                confidences.append(value)
        except (TypeError, ValueError):
            pass
    raw_text = " ".join(words)
    name = clean_ocr_character_name(raw_text)
    confidence = (
        sum(confidences) / len(confidences)
        if confidences
        else 0.0
    )
    return {
        "raw": raw_text,
        "name": name if is_plausible_character_name(name) else "",
        "confidence": confidence,
    }


def _extract_character_name(cv2, pytesseract, card, attribute):
    height, width = card.shape[:2]
    name_region = card[
        int(height * 0.40): int(height * 0.86),
        int(width * 0.12): int(width * 0.68),
    ]
    if name_region.size == 0:
        return "", "", 0.0, "名前認識失敗"

    enlarged_color = _enlarge_name_image(cv2, name_region)
    enlarged_gray = cv2.cvtColor(enlarged_color, cv2.COLOR_BGR2GRAY)
    enlarged_gray = cv2.createCLAHE(
        clipLimit=2.5,
        tileGridSize=(8, 8),
    ).apply(enlarged_gray)
    _, threshold_image = cv2.threshold(
        enlarged_gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    if threshold_image.mean() < 127:
        threshold_image = cv2.bitwise_not(threshold_image)

    variants = [
        {
            **_ocr_name_variant(
                pytesseract,
                _enlarge_name_image(
                    cv2,
                    _name_color_mask(cv2, name_region, attribute),
                ),
            ),
            "color_bonus": 24,
        },
        {
            **_ocr_name_variant(
                pytesseract,
                _enlarge_name_image(
                    cv2,
                    _name_color_mask(cv2, name_region),
                ),
            ),
            "color_bonus": 14,
        },
        {
            **_ocr_name_variant(pytesseract, enlarged_color),
            "color_bonus": 0,
        },
        {
            **_ocr_name_variant(pytesseract, threshold_image),
            "color_bonus": 0,
        },
    ]
    valid = [variant for variant in variants if variant["name"]]
    raw_names = []
    for variant in variants:
        if variant["raw"] and variant["raw"] not in raw_names:
            raw_names.append(variant["raw"])
    raw_text = " / ".join(raw_names)
    if not valid:
        return "", raw_text, 0.0, "名前認識失敗"

    for variant in valid:
        agreement = sum(
            SequenceMatcher(
                None,
                normalize_identity_name(variant["name"]),
                normalize_identity_name(other["name"]),
            ).ratio() >= 0.82
            for other in valid
        )
        variant["score"] = (
            variant["confidence"]
            + agreement * 12
            + len(normalize_identity_name(variant["name"]))
            + variant.get("color_bonus", 0)
        )
        variant["agreement"] = agreement
    selected = max(valid, key=lambda variant: variant["score"])
    status = "要目視確認"
    return (
        selected["name"],
        raw_text,
        selected["confidence"],
        status,
    )


def _ocr_single_line(pytesseract, image, language="jpn+eng"):
    return normalize_ocr_text(
        pytesseract.image_to_string(
            image,
            lang=language,
            config="--psm 7 -c preserve_interword_spaces=1",
        )
    )


def _extract_card_date_time(cv2, pytesseract, card):
    height, width = card.shape[:2]
    region = card[
        int(height * 0.03): int(height * 0.35),
        int(width * 0.04): int(width * 0.72),
    ]
    if region.size == 0:
        return None, ""
    variants = [
        _ocr_single_line(
            pytesseract,
            cv2.resize(
                region,
                None,
                fx=3.0,
                fy=3.0,
                interpolation=cv2.INTER_CUBIC,
            ),
        ),
        _ocr_single_line(pytesseract, _prepare_ocr_image(cv2, region)),
    ]
    for text in variants:
        parsed = find_date_time(text)
        if parsed:
            return parsed, " / ".join(
                value for value in variants if value
            )
    return None, " / ".join(value for value in variants if value)


def _extract_card_difficulty(cv2, pytesseract, card):
    """条件説明ではなく、カード右側の実難易度ラベルだけを読む。"""
    height, width = card.shape[:2]
    region = card[
        int(height * 0.38): int(height * 0.78),
        int(width * 0.52): int(width * 0.68),
    ]
    if region.size == 0:
        return "", ""
    variants = [
        _ocr_single_line(
            pytesseract,
            cv2.resize(
                region,
                None,
                fx=4.0,
                fy=4.0,
                interpolation=cv2.INTER_CUBIC,
            ),
        ),
        _ocr_single_line(pytesseract, _prepare_ocr_image(cv2, region)),
    ]
    results = [find_difficulty(text) for text in variants]
    results = [value for value in results if value]
    difficulty = ""
    if results:
        # 別処理が違う難易度を返した場合は、誤公開を防ぐため空欄にする。
        difficulty = results[0] if len(set(results)) == 1 else ""
    return difficulty, " / ".join(value for value in variants if value)


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
        int(height * 0.40): int(height * 0.86),
        int(width * 0.12): int(width * 0.68),
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
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    attribute, count = ranked[0]
    second_count = ranked[1][1]
    if count < 20 or count < second_count * 1.35:
        return ""
    return attribute


def _detect_card_regions(cv2, frame):
    """OCRに頼らず、カード上端の明るい横枠からカードを見つける。"""
    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    left = int(width * 0.015)
    right = int(width * 0.965)
    search_top = int(height * 0.36)
    search_bottom = int(height * 0.91)
    bright_counts = (
        gray[search_top:search_bottom, left:right] >= 145
    ).sum(axis=1)
    threshold = int((right - left) * 0.72)
    strong_rows = [
        search_top + index
        for index, count in enumerate(bright_counts)
        if int(count) >= threshold
    ]
    if not strong_rows:
        return []

    clusters = []
    for row in strong_rows:
        if not clusters or row - clusters[-1][-1] > 12:
            clusters.append([row])
        else:
            clusters[-1].append(row)

    tops = []
    for cluster in clusters:
        top = max(
            cluster,
            key=lambda row: int(bright_counts[row - search_top]),
        )
        if not tops or top - tops[-1] > int(height * 0.07):
            tops.append(top)

    card_height = int(height * 0.112)
    regions = []
    for top in tops:
        bottom = min(top + card_height, search_bottom)
        if bottom - top < int(card_height * 0.78):
            continue
        card = frame[top:bottom, left:right]
        if card.size:
            regions.append(card)
    return regions


def _extract_from_frame(cv2, pytesseract, frame, year):
    candidates = []
    failed_count = 0
    cards = _detect_card_regions(cv2, frame)
    for card in cards:
        date_time, raw_date = _extract_card_date_time(
            cv2,
            pytesseract,
            card,
        )
        if not date_time:
            failed_count += 1
            continue
        attribute = _infer_attribute(cv2, card)
        name, raw_name, name_confidence, ocr_status = _extract_character_name(
            cv2,
            pytesseract,
            card,
            attribute,
        )
        difficulty, raw_difficulty = _extract_card_difficulty(
            cv2,
            pytesseract,
            card,
        )
        height, width = card.shape[:2]
        name_region = card[
            int(height * 0.40): int(height * 0.86),
            int(width * 0.12): int(width * 0.68),
        ]
        visual_signature = _image_signature(cv2, name_region)
        date_text = (
            f"{date_time['date']} {date_time['start_time']}～"
            f"{date_time['date']} {date_time['end_time']}"
        )
        candidate = candidate_from_card_text(
            date_text,
            year,
            attribute=attribute,
            confidence=name_confidence,
            recognized_name=name,
            raw_name_text=raw_name,
            ocr_status=ocr_status,
            recognized_difficulty=difficulty,
            raw_difficulty_text=raw_difficulty,
            visual_signature=visual_signature,
        )
        if candidate:
            candidate["ocr_raw_date"] = raw_date
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
            pending_frame = None
            pending_hash = None
            pending_sharpness = -1.0
            while sampled_frame_count < MAX_SAMPLE_FRAMES:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame_index % step:
                    frame_index += 1
                    continue
                frame_index += 1
                game_viewport = _detect_game_viewport(cv2, frame)
                current_hash = _frame_hash(cv2, game_viewport)
                current_sharpness = _frame_sharpness(cv2, game_viewport)

                # 同じ画面が続く場合は、最初のフレームではなく
                # スクロール停止後の最も鮮明な1枚をOCRへ渡す。
                if pending_hash is not None and _hamming_distance(
                    pending_hash, current_hash
                ) <= 5:
                    if current_sharpness > pending_sharpness:
                        pending_frame = game_viewport.copy()
                        pending_hash = current_hash
                        pending_sharpness = current_sharpness
                    continue

                if pending_frame is not None:
                    sampled_frame_count += 1
                    candidates, failed = _extract_from_frame(
                        cv2, pytesseract, pending_frame, year
                    )
                    all_candidates.extend(candidates)
                    ocr_error_count += failed

                pending_frame = game_viewport.copy()
                pending_hash = current_hash
                pending_sharpness = current_sharpness

            if (
                pending_frame is not None
                and sampled_frame_count < MAX_SAMPLE_FRAMES
            ):
                sampled_frame_count += 1
                candidates, failed = _extract_from_frame(
                    cv2, pytesseract, pending_frame, year
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

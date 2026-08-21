import hashlib
import json
from datetime import date, datetime, time

import pandas as pd
import streamlit as st

from auth_manager import require_admin_authentication
from data_manager import (
    load_events,
    load_json,
    load_schedules,
    save_events,
    save_json,
    save_schedules,
)
from auto_updater import run_update
from github_storage import (
    GitHubStorageError,
    is_configured as github_is_configured,
    load_remote_json,
    save_remote_json,
)
from schedule_utils import (
    AVAILABILITY_PERIOD,
    AVAILABILITY_SCHEDULED,
    AVAILABILITY_TYPES,
    SCHEDULE_CATEGORIES,
    normalize_availability_type,
    normalize_schedule_category,
)
from video_schedule_extractor import (
    VideoScheduleError,
    candidate_identity as pending_candidate_identity,
    extract_video_schedule_candidates,
)


st.set_page_config(
    page_title="モンスト スケジュール管理",
    page_icon="🛠️",
    layout="wide",
)


ATTRIBUTES = ["火", "水", "木", "光", "闇"]
DIFFICULTIES = [
    "黎絶",
    "轟絶",
    "超究極",
    "超究極・兵",
    "爆絶",
    "超絶",
    "激究極",
    "究極",
    "星5制限",
    "極",
]
EVENT_CATEGORIES = [
    "定期コンテンツ",
    "コラボ・期間限定",
    "コラボガチャ",
    "コラボミッション",
    "ガチャ",
    "育成キャンペーン",
    "ゲーム内キャンペーン",
    "マルチキャンペーン",
    "ミッション",
    "周年CP",
    "獣神化情報",
    "期限",
]


require_admin_authentication()


def load_admin_json(filename, local_loader=None):
    if github_is_configured():
        return load_remote_json(filename)
    if local_loader:
        return local_loader()
    return load_json(filename)


def save_admin_json(filename, data, local_saver, commit_message):
    if github_is_configured():
        save_remote_json(filename, data, commit_message)
        return "GitHubへ保存しました。公開アプリは自動更新されます。"
    local_saver(data)
    return "ローカルJSONへ保存しました。"


def normalize_text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def validate_time(value):
    try:
        datetime.strptime(normalize_text(value), "%H:%M")
        return True
    except ValueError:
        return False


def validate_date(value):
    try:
        datetime.strptime(normalize_text(value), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def schedule_rows_from_editor(editor_data):
    rows = []
    errors = []

    for row_number, row in enumerate(editor_data.to_dict("records"), start=1):
        try:
            year = int(row.get("year"))
        except (TypeError, ValueError):
            errors.append(f"降臨データ{row_number}行目：yearが不正です。")
            continue

        date_value = normalize_text(row.get("date"))
        start_time = normalize_text(row.get("start_time"))
        end_time = normalize_text(row.get("end_time"))
        name = normalize_text(row.get("name"))
        quest_name = normalize_text(row.get("quest_name"))
        attribute = normalize_text(row.get("attribute"))
        difficulty = normalize_text(row.get("difficulty"))
        category = normalize_text(row.get("category"))
        category = normalize_schedule_category(category)
        group_name = normalize_text(row.get("group_name"))
        availability_type = normalize_availability_type(
            normalize_text(row.get("availability_type"))
        )
        period_end_date = normalize_text(row.get("period_end_date"))
        source_type = normalize_text(row.get("source_type")) or "manual"
        source_url = normalize_text(row.get("source_url"))
        published = bool(row.get("published", True))

        try:
            datetime.strptime(f"{year}/{date_value}", "%Y/%m/%d")
        except ValueError:
            errors.append(f"降臨データ{row_number}行目：日付が不正です。")

        if not validate_time(start_time) or not validate_time(end_time):
            errors.append(f"降臨データ{row_number}行目：時刻はHH:MM形式で入力してください。")
        if not name:
            errors.append(f"降臨データ{row_number}行目：キャラ名が空です。")
        if attribute not in ATTRIBUTES:
            errors.append(f"降臨データ{row_number}行目：属性が不正です。")
        if difficulty not in DIFFICULTIES:
            errors.append(f"降臨データ{row_number}行目：難易度が不正です。")
        if category not in SCHEDULE_CATEGORIES:
            errors.append(f"降臨データ{row_number}行目：カテゴリが不正です。")
        if availability_type not in AVAILABILITY_TYPES:
            errors.append(f"降臨データ{row_number}行目：開催方式が不正です。")
        if availability_type == AVAILABILITY_PERIOD:
            if not validate_date(period_end_date):
                errors.append(
                    f"降臨データ{row_number}行目："
                    "最終掲載日はYYYY-MM-DD形式で入力してください。"
                )
            else:
                try:
                    start_date = datetime.strptime(
                        f"{year}/{date_value}", "%Y/%m/%d"
                    ).date()
                    end_date = datetime.strptime(
                        period_end_date, "%Y-%m-%d"
                    ).date()
                    if end_date < start_date:
                        errors.append(
                            f"降臨データ{row_number}行目："
                            "最終掲載日が開始日より前です。"
                        )
                except ValueError:
                    pass

        rows.append({
            "year": year,
            "date": date_value,
            "start_time": start_time,
            "end_time": end_time,
            "name": name,
            "quest_name": quest_name,
            "attribute": attribute,
            "difficulty": difficulty,
            "category": category,
            "group_name": group_name,
            "availability_type": availability_type,
            "period_end_date": period_end_date,
            "source_type": source_type,
            "source_url": source_url,
            "confirmed_at": normalize_text(row.get("confirmed_at")),
            "published": published,
        })

    return rows, errors


def event_rows_from_editor(editor_data):
    rows = []
    errors = []

    for row_number, row in enumerate(editor_data.to_dict("records"), start=1):
        name = normalize_text(row.get("name"))
        short_name = normalize_text(row.get("short_name"))
        category = normalize_text(row.get("category"))
        start_date = normalize_text(row.get("start_date"))
        end_date = normalize_text(row.get("end_date"))
        start_time = normalize_text(row.get("start_time"))
        end_time = normalize_text(row.get("end_time"))
        daily_labels = normalize_text(row.get("daily_labels"))
        description = normalize_text(row.get("description"))
        source_type = normalize_text(row.get("source_type")) or "manual"
        source_url = normalize_text(row.get("source_url"))
        published = bool(row.get("published", True))

        if not name:
            errors.append(f"イベントデータ{row_number}行目：名称が空です。")
        if not short_name:
            errors.append(f"イベントデータ{row_number}行目：短縮表示名が空です。")
        if category not in EVENT_CATEGORIES:
            errors.append(f"イベントデータ{row_number}行目：カテゴリが不正です。")
        if not validate_date(start_date) or not validate_date(end_date):
            errors.append(f"イベントデータ{row_number}行目：日付はYYYY-MM-DD形式で入力してください。")
        elif start_date > end_date:
            errors.append(f"イベントデータ{row_number}行目：終了日が開始日より前です。")
        if start_time and not validate_time(start_time):
            errors.append(f"イベントデータ{row_number}行目：開始時刻はHH:MM形式で入力してください。")
        if end_time and not validate_time(end_time):
            errors.append(f"イベントデータ{row_number}行目：終了時刻はHH:MM形式で入力してください。")

        rows.append({
            "name": name,
            "short_name": short_name,
            "category": category,
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "daily_labels": daily_labels,
            "description": description,
            "source_type": source_type,
            "source_url": source_url,
            "confirmed_at": normalize_text(row.get("confirmed_at")),
            "published": published,
        })

    return rows, errors


def ensure_schedule_columns(schedules):
    defaults = {
        "quest_name": "",
        "group_name": "",
        "availability_type": AVAILABILITY_SCHEDULED,
        "period_end_date": "",
        "source_type": "manual",
        "source_url": "",
        "confirmed_at": "",
        "published": True,
    }
    results = []
    for schedule in schedules:
        normalized = {**defaults, **schedule}
        normalized["category"] = normalize_schedule_category(
            normalized.get("category")
        )
        normalized["availability_type"] = normalize_availability_type(
            normalized.get("availability_type")
        )
        results.append(normalized)
    return results


def ensure_event_columns(events):
    defaults = {
        "start_time": "",
        "end_time": "",
        "daily_labels": "",
        "description": "",
        "source_type": "manual",
        "source_url": "",
        "confirmed_at": "",
        "published": True,
    }
    return [{**defaults, **event} for event in events]


def show_candidate_status(filename, label):
    candidates = load_admin_json(filename)
    if not candidates:
        st.info(f"{label}の自動取得候補はまだありません。")
        return
    st.dataframe(candidates, use_container_width=True, hide_index=True)


def schedule_identity(schedule):
    return (
        int(schedule["year"]),
        schedule["date"],
        schedule["start_time"],
        schedule["name"],
    )


def event_identity(event):
    return (
        event["name"],
        event["start_date"],
        event["end_date"],
    )


def merge_unique(existing, additions, identity_function):
    merged = list(existing)
    positions = {
        identity_function(item): index
        for index, item in enumerate(merged)
    }
    for item in additions:
        identity = identity_function(item)
        if identity in positions:
            merged[positions[identity]] = item
        else:
            positions[identity] = len(merged)
            merged.append(item)
    return merged


def save_schedule_candidates(candidates):
    return save_admin_json(
        "schedule_candidates.json",
        candidates,
        lambda data: save_json("schedule_candidates.json", data),
        "Add descent candidates from game recording",
    )


def ensure_candidate_id(candidate, index=0):
    if candidate.get("candidate_id"):
        return str(candidate["candidate_id"])
    source = json.dumps(
        candidate,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(
        f"{index}|{source}".encode("utf-8")
    ).hexdigest()[:20]


def reset_schedule_candidate_editor():
    st.session_state.pop("schedule_candidate_editor", None)


def show_video_extraction_result(result):
    columns = st.columns(6)
    values = (
        ("自動補正", result.recognized_count),
        ("画像確認", result.manual_review_count),
        ("確認候補", len(result.candidates)),
        ("公開済み重複", result.published_duplicate_count),
        ("承認待ち重複", result.pending_duplicate_count),
        ("完全除外", result.rejected_candidate_count),
    )
    for column, (label, value) in zip(columns, values):
        column.metric(label, value)
    st.caption(
        f"確認フレーム {result.sampled_frame_count}枚／"
        f"動画内重複 {result.video_duplicate_count}件／"
        f"日付OCR未完成 {result.ocr_error_count}件／"
        f"動画識別子 {result.video_fingerprint[:12]}…"
    )


def clear_video_review_state():
    for key in (
        "video_review_candidates",
        "video_extraction_result",
        "video_review_editor",
        "video_review_select_all",
        "video_review_last_select_all",
        "video_review_preview_index",
    ):
        st.session_state.pop(key, None)


def video_review_candidate_label(candidate, index):
    date_value = candidate.get("date") or "日付未確定"
    name = candidate.get("name") or "名前未確定"
    mode = candidate.get("review_mode", "画像確認")
    return f"{index + 1}. {date_value}｜{name}｜{mode}"


def render_video_review_candidates():
    candidates = st.session_state.get("video_review_candidates", [])
    result = st.session_state.get("video_extraction_result")
    if not candidates:
        return

    st.markdown("##### 動画から切り出した一時確認候補")
    st.warning(
        "この段階ではJSONへ保存していません。"
        "切り出し画像を確認し、表を修正してから保存対象を選んでください。"
    )
    if result is not None:
        show_video_extraction_result(result)

    preview_index = st.selectbox(
        "確認する切り出し画像",
        options=list(range(len(candidates))),
        format_func=lambda index: video_review_candidate_label(
            candidates[index], index
        ),
        key="video_review_preview_index",
    )
    preview_candidate = candidates[preview_index]
    preview_image = preview_candidate.get("_preview_image")
    if preview_image:
        st.image(
            preview_image,
            caption=video_review_candidate_label(
                preview_candidate, preview_index
            ),
            use_container_width=True,
        )
    else:
        st.info("この候補には確認画像がありません。")

    select_all = st.checkbox(
        "確認候補をすべて保存対象にする",
        key="video_review_select_all",
    )
    last_select_all = st.session_state.get("video_review_last_select_all")
    if last_select_all is not None and last_select_all != select_all:
        st.session_state.pop("video_review_editor", None)
    st.session_state["video_review_last_select_all"] = select_all

    rows = []
    for index, candidate in enumerate(candidates):
        rows.append({
            "save": select_all,
            "candidate_id": ensure_candidate_id(candidate, index),
            "year": candidate.get("year"),
            "date": candidate.get("date", ""),
            "start_time": candidate.get("start_time", "12:00"),
            "end_time": candidate.get("end_time", "11:59"),
            "name": candidate.get("name", ""),
            "quest_name": candidate.get("quest_name", ""),
            "attribute": candidate.get("attribute", ""),
            "difficulty": candidate.get("difficulty", ""),
            "category": normalize_schedule_category(
                candidate.get("category")
            ),
            "group_name": candidate.get("group_name", ""),
            "availability_type": normalize_availability_type(
                candidate.get("availability_type")
            ),
            "period_end_date": candidate.get("period_end_date", ""),
            "review_mode": candidate.get("review_mode", "画像確認"),
            "ocr_status": candidate.get("ocr_status", ""),
            "source_type": "game",
            "source_url": "",
            "confirmed_at": "",
            "published": False,
        })

    editor = st.data_editor(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        key="video_review_editor",
        column_config={
            "save": st.column_config.CheckboxColumn("保存対象"),
            "candidate_id": None,
            "year": st.column_config.NumberColumn(
                "year", min_value=2020, max_value=2100, step=1
            ),
            "attribute": st.column_config.SelectboxColumn(
                "属性", options=[""] + ATTRIBUTES
            ),
            "difficulty": st.column_config.SelectboxColumn(
                "難易度", options=[""] + DIFFICULTIES
            ),
            "category": st.column_config.SelectboxColumn(
                "カテゴリ", options=SCHEDULE_CATEGORIES
            ),
            "availability_type": st.column_config.SelectboxColumn(
                "開催方式", options=AVAILABILITY_TYPES
            ),
            "review_mode": st.column_config.TextColumn(
                "判定方法", disabled=True
            ),
            "ocr_status": st.column_config.TextColumn(
                "確認項目", disabled=True
            ),
            "source_type": None,
            "source_url": None,
            "confirmed_at": None,
            "published": None,
        },
    )

    save_column, discard_column = st.columns(2)
    with save_column:
        save_clicked = st.button(
            "選択した修正済み候補を承認待ちへ保存",
            type="primary",
        )
    with discard_column:
        discard_clicked = st.button("今回の一時候補を破棄")

    if discard_clicked:
        st.session_state["reset_video_review_state"] = True
        st.session_state["admin_flash_success"] = (
            "動画の一時確認候補を破棄しました。JSONは変更していません。"
        )
        st.rerun()

    if not save_clicked:
        return

    selected = editor[editor["save"] == True].copy()
    if selected.empty:
        st.warning("承認待ちへ保存する候補を選択してください。")
        return

    selected_core = selected.drop(
        columns=["save", "review_mode", "ocr_status"]
    )
    additions, errors = schedule_rows_from_editor(selected_core)
    if errors:
        for error in errors:
            st.error(error)
        return

    candidate_by_id = {
        ensure_candidate_id(candidate, index): candidate
        for index, candidate in enumerate(candidates)
    }
    selected_records = selected.to_dict("records")
    metadata_fields = (
        "candidate_id",
        "review_reason",
        "ocr_confidence",
        "ocr_raw_name",
        "ocr_raw_difficulty",
        "ocr_raw_date",
        "ocr_end_date",
        "ocr_status",
        "ocr_votes",
        "visual_signature",
        "card_signature",
        "video_fingerprint",
        "fetched_at",
        "review_mode",
    )
    for addition, selected_row in zip(additions, selected_records):
        candidate_id = str(selected_row["candidate_id"])
        source_candidate = candidate_by_id.get(candidate_id, {})
        for field in metadata_fields:
            if field in source_candidate:
                addition[field] = source_candidate[field]
        addition["candidate_id"] = candidate_id
        addition["source_type"] = "game"
        addition["published"] = False

    try:
        pending = load_admin_json("schedule_candidates.json")
        merged = merge_unique(
            pending,
            additions,
            pending_candidate_identity,
        )
        message = save_schedule_candidates(merged)
        st.session_state["reset_video_review_state"] = True
        st.session_state.pop("schedule_candidate_editor", None)
        st.session_state["admin_flash_success"] = (
            f"{message} 修正済み候補{len(additions)}件を"
            "承認待ちへ保存しました。"
        )
        st.rerun()
    except GitHubStorageError as error:
        st.error(str(error))


def import_schedule_candidates_from_video():
    if st.session_state.pop("reset_video_review_state", False):
        clear_video_review_state()

    st.markdown("#### アプリ画面録画から降臨候補を取得")
    st.caption(
        "MP4・MOV（100MB以下／3分以内）に対応します。"
        "動画は処理中だけ一時保存し、処理後に削除します。"
    )
    left, right = st.columns([1, 3])
    with left:
        recording_start_date = st.date_input(
            "録画内の最初の日程",
            value=date.today(),
            help=(
                "録画で最初に表示されるゲーム日を指定します。"
                "この日から14日を外れたOCR日付は保存しません。"
            ),
        )
    with right:
        uploaded_video = st.file_uploader(
            "モンストアプリのスケジュール画面録画",
            type=["mp4", "mov", "m4v"],
            help="画面をゆっくり一方向にスクロールした録画を選択してください。",
        )

    if st.button(
        "動画から降臨候補を抽出",
        type="primary",
        disabled=uploaded_video is None,
    ):
        try:
            video_bytes = uploaded_video.getvalue()
            published = ensure_schedule_columns(
                load_admin_json("schedules.json", load_schedules)
            )
            pending = load_admin_json("schedule_candidates.json")
            with st.spinner(
                "動画を解析しています。録画時間によって1～2分ほどかかります..."
            ):
                result = extract_video_schedule_candidates(
                    video_bytes=video_bytes,
                    year=recording_start_date.year,
                    recording_start_date=recording_start_date,
                    published_schedules=published,
                    pending_candidates=pending,
                )
            if result.candidates:
                st.session_state["video_review_candidates"] = (
                    result.candidates
                )
                st.session_state["video_extraction_result"] = result
                st.session_state.pop("video_review_editor", None)
                st.session_state.pop("video_review_select_all", None)
                st.session_state.pop("video_review_last_select_all", None)
                st.success(
                    f"切り出し画像付きの一時確認候補"
                    f"{len(result.candidates)}件を作成しました。"
                )
            else:
                st.info("確認できる一時候補はありませんでした。")
        except (VideoScheduleError, GitHubStorageError) as error:
            st.error(str(error))
        except Exception as error:
            st.error(
                "動画を解析できませんでした。録画を短くして再度お試しください。"
                f"（詳細：{error}）"
            )

    render_video_review_candidates()


def review_schedule_candidates():
    if st.session_state.pop("reset_schedule_candidate_bulk_delete", False):
        st.session_state.pop("schedule_candidate_delete_all", None)
        st.session_state.pop("schedule_candidate_editor", None)

    candidates = load_admin_json("schedule_candidates.json")
    if not candidates:
        st.info("降臨の自動取得候補はまだありません。")
        return

    delete_all = st.checkbox(
        "公開しない候補をすべて削除対象にする",
        key="schedule_candidate_delete_all",
        on_change=reset_schedule_candidate_editor,
    )
    st.caption(
        "一括選択後も、残したい候補の「削除」チェックは個別に外せます。"
    )

    rows = []
    for index, candidate in enumerate(candidates):
        candidate_id = ensure_candidate_id(candidate, index)
        rows.append({
            "approve": False,
            "delete": delete_all,
            "candidate_id": candidate_id,
            "year": candidate.get("year"),
            "date": candidate.get("date", ""),
            "start_time": candidate.get("start_time", ""),
            "end_time": candidate.get("end_time", ""),
            "name": candidate.get("name", ""),
            "quest_name": candidate.get("quest_name", ""),
            "attribute": candidate.get("attribute", ""),
            "difficulty": candidate.get("difficulty", ""),
            "category": candidate.get("category", "high_difficulty"),
            "group_name": candidate.get("group_name", ""),
            "availability_type": normalize_availability_type(
                candidate.get("availability_type")
            ),
            "period_end_date": candidate.get("period_end_date", ""),
            "source_type": candidate.get("source_type", "official"),
            "source_url": candidate.get("source_url", ""),
            "ocr_raw_name": candidate.get("ocr_raw_name", ""),
            "ocr_raw_difficulty": candidate.get(
                "ocr_raw_difficulty", ""
            ),
            "ocr_raw_date": candidate.get("ocr_raw_date", ""),
            "ocr_confidence": candidate.get("ocr_confidence"),
            "ocr_status": candidate.get("ocr_status", ""),
            "ocr_votes": candidate.get("ocr_votes"),
            "review_reason": candidate.get("review_reason", ""),
            "confirmed_at": candidate.get("confirmed_at", ""),
            "published": True,
        })

    editor = st.data_editor(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        key="schedule_candidate_editor",
        column_config={
            "approve": st.column_config.CheckboxColumn("承認"),
            "delete": st.column_config.CheckboxColumn("削除"),
            "candidate_id": None,
            "attribute": st.column_config.SelectboxColumn("属性", options=ATTRIBUTES),
            "difficulty": st.column_config.SelectboxColumn("難易度", options=DIFFICULTIES),
            "category": st.column_config.SelectboxColumn(
                "カテゴリ", options=SCHEDULE_CATEGORIES
            ),
            "group_name": st.column_config.TextColumn(
                "掲載グループ",
                help="例：ブルーロックコラボ、モンスト夏休み2026",
            ),
            "availability_type": st.column_config.SelectboxColumn(
                "開催方式", options=AVAILABILITY_TYPES
            ),
            "period_end_date": st.column_config.TextColumn(
                "最終掲載日",
                help=(
                    "期間中常設の場合のみ入力します。"
                    "2026-08-19なら、8/19 12:00～翌11:59の行まで掲載します。"
                ),
            ),
            "source_url": st.column_config.LinkColumn("公式記事"),
            "ocr_raw_name": st.column_config.TextColumn(
                "OCR原文",
                disabled=True,
                help="キャラ名領域を複数の方法で読み取った元データです。",
            ),
            "ocr_confidence": st.column_config.NumberColumn(
                "OCR内部評価",
                disabled=True,
                format="%.1f",
                help=(
                    "OCR処理内の比較用数値で、"
                    "キャラ名の正答率を保証する値ではありません。"
                ),
            ),
            "ocr_status": st.column_config.TextColumn(
                "OCR判定",
                disabled=True,
            ),
            "ocr_votes": st.column_config.NumberColumn(
                "検出回数",
                disabled=True,
                format="%d",
            ),
            "ocr_raw_difficulty": st.column_config.TextColumn(
                "難易度OCR原文",
                disabled=True,
            ),
            "ocr_raw_date": st.column_config.TextColumn(
                "日時OCR原文",
                disabled=True,
            ),
            "review_reason": st.column_config.TextColumn(
                "確認理由", disabled=True
            ),
        },
    )
    selected = editor[editor["approve"] == True].drop(
        columns=["approve", "delete"]
    )
    selected_delete_ids = set(
        editor.loc[editor["delete"] == True, "candidate_id"].astype(str)
    )

    approve_column, delete_column = st.columns(2)
    with approve_column:
        approve_clicked = st.button(
            "選択した降臨候補を承認・公開",
            type="primary",
        )
    with delete_column:
        delete_clicked = st.button("選択した承認待ち候補を削除")

    if delete_clicked:
        if not selected_delete_ids:
            st.warning("削除する承認待ち候補を選択してください。")
            return
        remaining = [
            candidate
            for index, candidate in enumerate(candidates)
            if ensure_candidate_id(candidate, index) not in selected_delete_ids
        ]
        try:
            message = save_schedule_candidates(remaining)
            st.session_state.pop("schedule_candidate_editor", None)
            st.session_state["reset_schedule_candidate_bulk_delete"] = True
            st.session_state["admin_flash_success"] = (
                f"{message} 承認待ち候補を"
                f"{len(candidates) - len(remaining)}件削除しました。"
            )
            st.rerun()
        except GitHubStorageError as error:
            st.error(str(error))
        return

    if approve_clicked:
        if selected.empty:
            st.warning("承認する候補を選択してください。")
            return
        additions, errors = schedule_rows_from_editor(selected)
        if errors:
            for error in errors:
                st.error(error)
            return

        confirmed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        for addition in additions:
            addition["confirmed_at"] = confirmed_at
            addition["source_type"] = "verified"
            addition["published"] = True

        current = ensure_schedule_columns(
            load_admin_json("schedules.json", load_schedules)
        )
        merged = merge_unique(current, additions, schedule_identity)
        message = save_admin_json(
            "schedules.json",
            merged,
            save_schedules,
            "Approve descent schedule candidates",
        )
        approved_ids = set(selected["candidate_id"].astype(str))
        remaining = [
            candidate
            for index, candidate in enumerate(candidates)
            if ensure_candidate_id(candidate, index) not in approved_ids
        ]
        save_schedule_candidates(remaining)
        st.session_state.pop("schedule_editor", None)
        st.session_state.pop("schedule_candidate_editor", None)
        st.session_state["admin_flash_success"] = message
        st.rerun()


def review_event_candidates():
    candidates = load_admin_json("event_candidates.json")
    if not candidates:
        st.info("イベントの自動取得候補はまだありません。")
        return

    rows = []
    for candidate in candidates:
        rows.append({
            "approve": False,
            "name": candidate.get("name", ""),
            "short_name": candidate.get("short_name", ""),
            "category": candidate.get("category", ""),
            "start_date": candidate.get("start_date", ""),
            "end_date": candidate.get("end_date", ""),
            "start_time": candidate.get("start_time", ""),
            "end_time": candidate.get("end_time", ""),
            "daily_labels": candidate.get("daily_labels", ""),
            "description": candidate.get("description", ""),
            "source_type": candidate.get("source_type", "official"),
            "source_url": candidate.get("source_url", ""),
            "review_reason": candidate.get("review_reason", ""),
            "confirmed_at": candidate.get("confirmed_at", ""),
            "published": True,
        })

    editor = st.data_editor(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        key="event_candidate_editor",
        column_config={
            "approve": st.column_config.CheckboxColumn("承認"),
            "category": st.column_config.SelectboxColumn(
                "カテゴリ", options=EVENT_CATEGORIES
            ),
            "start_time": st.column_config.TextColumn("開始時刻"),
            "end_time": st.column_config.TextColumn("終了時刻"),
            "daily_labels": st.column_config.TextColumn(
                "日別表示",
                help="開始日から順に、闇・木・光のように区切って入力します。",
            ),
            "source_url": st.column_config.LinkColumn("公式記事"),
            "review_reason": st.column_config.TextColumn(
                "確認理由", disabled=True
            ),
        },
    )
    selected = editor[editor["approve"] == True].drop(columns=["approve"])
    if st.button("選択したイベント候補を承認・公開", type="primary"):
        if selected.empty:
            st.warning("承認する候補を選択してください。")
            return
        additions, errors = event_rows_from_editor(selected)
        if errors:
            for error in errors:
                st.error(error)
            return

        confirmed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        for addition in additions:
            addition["confirmed_at"] = confirmed_at
            addition["source_type"] = "verified"
            addition["published"] = True

        current = ensure_event_columns(load_admin_json("events.json", load_events))
        merged = merge_unique(current, additions, event_identity)
        message = save_admin_json(
            "events.json",
            merged,
            save_events,
            "Approve event candidates",
        )
        st.session_state.pop("event_editor", None)
        st.session_state.pop("event_candidate_editor", None)
        st.session_state["admin_flash_success"] = message
        st.rerun()


st.title("モンスト スケジュール管理")
flash_success = st.session_state.pop("admin_flash_success", None)
if flash_success:
    st.success(flash_success)
st.warning(
    "この画面は管理者用です。公開アプリではなく、あなたのPCでのみ起動してください。"
)
st.caption(
    "保存前に入力内容を検証し、元のJSONはbackupsフォルダへ自動保存します。"
)
if github_is_configured():
    st.success("オンライン保存：GitHub連携済み")
else:
    st.info("ローカル保存モード：GitHub連携は未設定です。")

schedule_tab, event_tab, candidate_tab = st.tabs([
    "降臨管理",
    "イベント管理",
    "自動取得候補・失敗ログ",
])


with schedule_tab:
    st.subheader("降臨情報の編集・登録")
    try:
        schedule_data = ensure_schedule_columns(
            load_admin_json("schedules.json", load_schedules)
        )
    except GitHubStorageError as error:
        st.error(str(error))
        st.stop()
    schedule_editor = st.data_editor(
        pd.DataFrame(schedule_data),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="schedule_editor",
        column_config={
            "attribute": st.column_config.SelectboxColumn("属性", options=ATTRIBUTES),
            "difficulty": st.column_config.SelectboxColumn("難易度", options=DIFFICULTIES),
            "category": st.column_config.SelectboxColumn(
                "カテゴリ", options=SCHEDULE_CATEGORIES
            ),
            "group_name": st.column_config.TextColumn(
                "掲載グループ",
                help="同じコラボ・期間限定降臨をまとめる名前です。",
            ),
            "availability_type": st.column_config.SelectboxColumn(
                "開催方式", options=AVAILABILITY_TYPES
            ),
            "period_end_date": st.column_config.TextColumn(
                "最終掲載日",
                help=(
                    "期間中常設の場合のみ入力します。"
                    "2026-08-19なら、8/19 12:00～翌11:59の行まで掲載します。"
                ),
            ),
            "source_type": st.column_config.SelectboxColumn(
                "情報源種別",
                options=["manual", "game", "official", "external", "verified"],
            ),
            "published": st.column_config.CheckboxColumn("公開"),
        },
    )

    schedule_rows, schedule_errors = schedule_rows_from_editor(schedule_editor)
    if schedule_errors:
        for error in schedule_errors:
            st.error(error)

    schedule_json = json.dumps(schedule_rows, ensure_ascii=False, indent=4)
    left, right = st.columns(2)
    with left:
        if st.button("降臨データを保存", type="primary", disabled=bool(schedule_errors)):
            try:
                message = save_admin_json(
                    "schedules.json",
                    schedule_rows,
                    save_schedules,
                    "Update descent schedules from admin",
                )
                st.success(message)
            except GitHubStorageError as error:
                st.error(str(error))
    with right:
        st.download_button(
            "降臨JSONをダウンロード",
            data=schedule_json,
            file_name="schedules.json",
            mime="application/json",
            disabled=bool(schedule_errors),
        )


with event_tab:
    st.subheader("イベント・キャンペーン情報の編集・登録")
    try:
        event_data = ensure_event_columns(
            load_admin_json("events.json", load_events)
        )
    except GitHubStorageError as error:
        st.error(str(error))
        st.stop()
    event_editor = st.data_editor(
        pd.DataFrame(event_data),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="event_editor",
        column_config={
            "category": st.column_config.SelectboxColumn(
                "カテゴリ", options=EVENT_CATEGORIES
            ),
            "start_time": st.column_config.TextColumn("開始時刻"),
            "end_time": st.column_config.TextColumn("終了時刻"),
            "daily_labels": st.column_config.TextColumn(
                "日別表示",
                help="開始日から順に、闇・木・光のように区切って入力します。",
            ),
            "source_type": st.column_config.SelectboxColumn(
                "情報源種別",
                options=["manual", "game", "official", "external", "verified"],
            ),
            "published": st.column_config.CheckboxColumn("公開"),
        },
    )

    event_rows, event_errors = event_rows_from_editor(event_editor)
    if event_errors:
        for error in event_errors:
            st.error(error)

    event_json = json.dumps(event_rows, ensure_ascii=False, indent=4)
    left, right = st.columns(2)
    with left:
        if st.button("イベントデータを保存", type="primary", disabled=bool(event_errors)):
            try:
                message = save_admin_json(
                    "events.json",
                    event_rows,
                    save_events,
                    "Update events from admin",
                )
                st.success(message)
            except GitHubStorageError as error:
                st.error(str(error))
    with right:
        st.download_button(
            "イベントJSONをダウンロード",
            data=event_json,
            file_name="events.json",
            mime="application/json",
            disabled=bool(event_errors),
        )


with candidate_tab:
    st.subheader("自動取得候補")
    import_schedule_candidates_from_video()
    st.divider()
    st.markdown("#### 公式ニュースから取得")
    if st.button("公式ニュースから候補を取得", type="primary"):
        with st.spinner("公式ニュースを確認しています..."):
            try:
                result = run_update()
                if github_is_configured():
                    for filename in (
                        "schedule_candidates.json",
                        "event_candidates.json",
                        "fetch_errors.json",
                        "fetch_status.json",
                    ):
                        save_remote_json(
                            filename,
                            load_json(filename),
                            f"Update {filename} from admin",
                        )
                # data_editorが前回の候補一覧を保持しないようにする。
                st.session_state.pop("schedule_candidate_editor", None)
                st.session_state.pop("event_candidate_editor", None)
                st.success(
                    "取得完了："
                    f"降臨候補 {result['schedule_candidate_count']}件、"
                    f"イベント候補 {result['event_candidate_count']}件、"
                    "終了済み除外 "
                    f"{result.get('expired_schedule_count', 0) + result['expired_event_count']}件、"
                    f"エラー {result['error_count']}件"
                )
            except Exception as error:
                st.error(f"自動取得を実行できませんでした：{error}")

    schedule_candidate_tab, event_candidate_tab, log_tab = st.tabs([
        "降臨候補",
        "イベント候補",
        "失敗ログ",
    ])
    with schedule_candidate_tab:
        review_schedule_candidates()
    with event_candidate_tab:
        review_event_candidates()
    with log_tab:
        statuses = load_admin_json("fetch_status.json")
        if statuses:
            st.caption("直近の取得状況")
            st.dataframe(statuses, use_container_width=True, hide_index=True)

        logs = load_admin_json("fetch_errors.json")
        if logs:
            st.caption("取得失敗ログ")
            st.dataframe(logs, use_container_width=True, hide_index=True)
        else:
            st.info("取得失敗ログはありません。")

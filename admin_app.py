import hashlib
import json
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from auth_manager import require_admin_authentication
from data_manager import (
    load_events,
    load_json,
    load_quest_master,
    load_schedules,
    save_events,
    save_json,
    save_quest_master,
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
from quest_master import (
    KANA_GROUPS,
    LIMITED_MASTER_CATEGORIES,
    add_candidate_image_reference,
    card_reference_is_learnable,
    delete_quest_master,
    master_expired,
    normalize_quest_master,
    normalize_quest_master_record,
    parse_master_bulk_entries,
    quest_master_kana_group,
    quest_master_key,
    schedule_from_master,
    search_quest_master,
    upsert_quest_master,
)
from video_schedule_extractor import (
    OCR_MODE_FAST,
    OCR_MODE_PRECISE,
    VideoScheduleError,
    candidate_identity as pending_candidate_identity,
    deduplicate_resolved_candidates,
    extract_screenshot_schedule_candidates,
    extract_video_schedule_candidates,
    resolve_candidate_with_master,
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
    "超絶・廻",
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
        quest_id = normalize_text(row.get("quest_id"))
        end_next_day = bool(row.get("end_next_day", False))

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
            "quest_id": quest_id,
            "year": year,
            "date": date_value,
            "start_time": start_time,
            "end_time": end_time,
            "end_next_day": end_next_day,
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
        "quest_id": "",
        "end_next_day": False,
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
        schedule.get("quest_id") or schedule["name"],
        schedule.get("difficulty", ""),
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


def save_quest_master_records(records, commit_message="Update quest master"):
    return save_admin_json(
        "quest_master.json",
        normalize_quest_master(records),
        save_quest_master,
        commit_message,
    )


def quest_master_label(record):
    reading = (
        f"（{record['name_reading']}）"
        if record.get("name_reading") else ""
    )
    group = f"｜{record['group_name']}" if record.get("group_name") else ""
    expired = "｜期限切れ" if master_expired(record) else ""
    image_count = len(record.get("image_references", []))
    image_text = f"｜画像{image_count}件" if image_count else "｜画像未登録"
    return (
        f"{record.get('name', '')}{reading}｜{record.get('attribute', '')}｜"
        f"{record.get('difficulty', '')}｜{record.get('category', '')}"
        f"{group}{image_text}{expired}"
    )


def render_quest_master_management():
    try:
        records = normalize_quest_master(
            load_admin_json("quest_master.json", load_quest_master)
        )
        schedules = ensure_schedule_columns(
            load_admin_json("schedules.json", load_schedules)
        )
    except GitHubStorageError as error:
        st.error(str(error))
        return

    st.subheader("降臨マスター")
    st.caption(
        "一度承認した降臨を名前・属性・難易度・カテゴリと一緒に保存します。"
        "次回からは検索して、掲載日と開始時間だけで日程へ追加できます。"
    )
    expired_count = sum(master_expired(record) for record in records)
    normal_count = sum(
        record.get("category") not in LIMITED_MASTER_CATEGORIES
        for record in records
    )
    limited_count = len(records) - normal_count
    metric_columns = st.columns(4)
    for column, (label, value) in zip(metric_columns, (
        ("登録数", len(records)),
        ("通常・高難易度", normal_count),
        ("コラボ・期間限定", limited_count),
        ("期限切れ", expired_count),
    )):
        column.metric(label, value)

    if st.button("公開済み降臨からマスターを初期登録・補完"):
        merged, added, updated, skipped = upsert_quest_master(
            records,
            schedules,
        )
        try:
            message = save_quest_master_records(
                merged,
                "Initialize quest master from published schedules",
            )
            st.session_state["admin_flash_success"] = (
                f"{message} マスター追加{added}件・更新{updated}件"
                f"・対象外{skipped}件。"
            )
            st.rerun()
        except GitHubStorageError as error:
            st.error(str(error))

    st.markdown("#### 抽出前に降臨をマスターへ先行登録")
    st.caption(
        "通常降臨は名前・属性・難易度・降臨カテゴリだけで登録できます。"
        "登録後のスクリーンショット抽出から補正候補として使用します。"
    )
    registration_default_tab = st.session_state.pop(
        "quest_master_registration_default_tab",
        "1体ずつ登録",
    )
    single_tab, bulk_tab = st.tabs(
        ["1体ずつ登録", "まとめて登録"],
        default=registration_default_tab,
    )
    with single_tab:
        with st.form("manual_quest_master_form", clear_on_submit=True):
            manual_name = st.text_input("名前")
            manual_name_reading = st.text_input(
                "読み（任意）",
                help=(
                    "漢字で始まる名前は、五十音分類に使う先頭1文字だけでも"
                    "登録できます。フルの読みを入れると読みでも検索できます。"
                ),
            )
            manual_attribute = st.selectbox("属性", ATTRIBUTES)
            manual_difficulty = st.selectbox("難易度", DIFFICULTIES)
            manual_category = st.selectbox(
                "降臨カテゴリ",
                SCHEDULE_CATEGORIES,
                index=SCHEDULE_CATEGORIES.index("通常降臨"),
            )
            manual_group = st.text_input(
                "掲載グループ（コラボ・期間限定のみ任意）"
            )
            manual_period_end = st.text_input(
                "期間終了日（コラボ・期間限定のみ／YYYY-MM-DD）"
            )
            manual_submit = st.form_submit_button(
                "この降臨をマスターへ登録",
                type="primary",
            )
        if manual_submit:
            errors = []
            if not manual_name.strip():
                errors.append("名前を入力してください。")
            limited = manual_category in LIMITED_MASTER_CATEGORIES
            if limited and manual_period_end and not validate_date(
                manual_period_end
            ):
                errors.append(
                    "期間終了日はYYYY-MM-DD形式で入力してください。"
                )
            if errors:
                for error in errors:
                    st.error(error)
            else:
                additions = [{
                    "name": manual_name,
                    "name_reading": manual_name_reading,
                    "attribute": manual_attribute,
                    "difficulty": manual_difficulty,
                    "category": manual_category,
                    "group_name": manual_group if limited else "",
                    "availability_type": AVAILABILITY_SCHEDULED,
                    "period_end_date": manual_period_end if limited else "",
                    "source_type": "manual",
                    "published": True,
                }]
                merged, added, updated, skipped = upsert_quest_master(
                    records,
                    additions,
                )
                try:
                    message = save_quest_master_records(
                        merged,
                        "Register quest master before extraction",
                    )
                    st.session_state["admin_flash_success"] = (
                        f"{message} {manual_name}をマスターへ"
                        f"{'追加' if added else '更新'}しました。"
                    )
                    st.session_state["admin_force_default_tab"] = "降臨マスター"
                    st.rerun()
                except GitHubStorageError as error:
                    st.error(str(error))

    with bulk_tab:
        with st.form("bulk_quest_master_form", clear_on_submit=True):
            bulk_category = st.selectbox(
                "登録する降臨カテゴリ（全行共通）",
                SCHEDULE_CATEGORIES,
                index=SCHEDULE_CATEGORIES.index("通常降臨"),
                key="bulk_master_default_category",
            )
            bulk_group = st.text_input(
                "共通の掲載グループ（任意）",
                key="bulk_master_group",
            )
            bulk_period_end = st.text_input(
                "共通の期間終了日（任意／YYYY-MM-DD）",
                key="bulk_master_period_end",
            )
            bulk_text = st.text_area(
                "1行に1体入力",
                placeholder=(
                    "スノーマン｜木｜究極\n"
                    "仙丹｜木｜超絶｜せ"
                ),
                help=(
                    "名前｜属性｜難易度の順です。4項目目は任意の読みで、"
                    "先頭1文字だけでも構いません。降臨カテゴリは上で選んだ"
                    "内容を全行に適用します。縦線の代わりにカンマも使えます。"
                ),
                height=180,
            )
            bulk_submit = st.form_submit_button(
                "入力した降臨をまとめて登録",
                type="primary",
            )
        if bulk_submit:
            entries = parse_master_bulk_entries(
                bulk_text,
                bulk_category,
            )
            registration_results = []
            prepared = []
            existing_keys = {
                quest_master_key(record)
                for record in records
            }
            seen_input_keys = {}
            period_error = (
                bool(bulk_period_end)
                and not validate_date(bulk_period_end)
            )

            if not entries:
                registration_results.append({
                    "行": "-",
                    "登録内容": "未入力",
                    "判定": "エラー",
                    "詳細": "登録する降臨を入力してください。",
                })

            for entry in entries:
                line_number = entry["line_number"]
                addition = entry.get("record")
                if addition is None:
                    registration_results.append({
                        "行": line_number,
                        "登録内容": entry.get("name") or entry["raw_line"],
                        "判定": "エラー",
                        "詳細": entry.get("error") or "入力形式が不正です。",
                    })
                    continue

                registration_text = "｜".join((
                    addition.get("name", ""),
                    addition.get("attribute", ""),
                    addition.get("difficulty", ""),
                ))
                row_errors = []
                if addition.get("attribute") not in ATTRIBUTES:
                    row_errors.append(
                        "属性は火・水・木・光・闇から選んでください。"
                    )
                if addition.get("difficulty") not in DIFFICULTIES:
                    row_errors.append("難易度が登録対象外です。")
                if addition.get("category") not in SCHEDULE_CATEGORIES:
                    row_errors.append("上部で選択した降臨カテゴリが不正です。")
                if period_error:
                    row_errors.append(
                        "共通の期間終了日はYYYY-MM-DD形式で入力してください。"
                    )
                if row_errors:
                    registration_results.append({
                        "行": line_number,
                        "登録内容": registration_text,
                        "判定": "エラー",
                        "詳細": " ".join(row_errors),
                    })
                    continue

                key = quest_master_key(addition)
                if key in seen_input_keys:
                    registration_results.append({
                        "行": line_number,
                        "登録内容": registration_text,
                        "判定": "入力重複",
                        "詳細": (
                            f"{seen_input_keys[key]}行目と名前・難易度が重複しています。"
                        ),
                    })
                    continue
                seen_input_keys[key] = line_number

                limited = addition["category"] in LIMITED_MASTER_CATEGORIES
                prepared.append({
                    **addition,
                    "group_name": bulk_group if limited else "",
                    "availability_type": AVAILABILITY_SCHEDULED,
                    "period_end_date": bulk_period_end if limited else "",
                    "source_type": "manual",
                    "published": True,
                })
                registration_results.append({
                    "行": line_number,
                    "登録内容": registration_text,
                    "判定": "既存更新" if key in existing_keys else "新規追加",
                    "詳細": (
                        "同じ名前・難易度の登録内容を更新します。"
                        if key in existing_keys
                        else "新しいマスターとして追加します。"
                    ),
                })

            if prepared:
                merged, added, updated, skipped = upsert_quest_master(
                    records,
                    prepared,
                )
                try:
                    message = save_quest_master_records(
                        merged,
                        "Bulk register quest master before extraction",
                    )
                    st.session_state[
                        "bulk_master_registration_results"
                    ] = registration_results
                    result_counts = {
                        status: sum(
                            result["判定"] == status
                            for result in registration_results
                        )
                        for status in (
                            "新規追加", "既存更新", "入力重複", "エラー"
                        )
                    }
                    st.session_state["admin_flash_success"] = (
                        f"{message} 新規追加{added}件・既存更新{updated}件・"
                        f"入力重複{result_counts['入力重複']}件・"
                        f"エラー{result_counts['エラー'] + skipped}件。"
                    )
                    st.session_state["admin_force_default_tab"] = "降臨マスター"
                    st.session_state[
                        "quest_master_registration_default_tab"
                    ] = "まとめて登録"
                    st.rerun()
                except GitHubStorageError as error:
                    for result in registration_results:
                        if result["判定"] in ("新規追加", "既存更新"):
                            result["判定"] = "エラー"
                            result["詳細"] = f"保存できませんでした：{error}"
                    st.session_state[
                        "bulk_master_registration_results"
                    ] = registration_results
                    st.error(str(error))
            else:
                st.session_state[
                    "bulk_master_registration_results"
                ] = registration_results

        bulk_results = st.session_state.get(
            "bulk_master_registration_results",
            [],
        )
        if bulk_results:
            st.markdown("##### 直近のまとめて登録結果")
            status_counts = {
                status: sum(
                    result["判定"] == status
                    for result in bulk_results
                )
                for status in ("新規追加", "既存更新", "入力重複", "エラー")
            }
            st.caption(
                f"新規追加 {status_counts['新規追加']}件 ／ "
                f"既存更新 {status_counts['既存更新']}件 ／ "
                f"入力重複 {status_counts['入力重複']}件 ／ "
                f"エラー {status_counts['エラー']}件"
            )
            st.dataframe(
                pd.DataFrame(bulk_results),
                use_container_width=True,
                hide_index=True,
                height=min(420, 38 * len(bulk_results) + 38),
            )

    st.markdown("#### 登録済み降臨を検索して日程へ追加")
    search_column, kana_column, expired_column = st.columns([2, 1, 1])
    with search_column:
        query = st.text_input(
            "名前・読み・難易度・カテゴリで検索",
            key="quest_master_search",
        )
    with kana_column:
        kana_group = st.selectbox(
            "五十音",
            options=["すべて", *KANA_GROUPS],
            key="quest_master_kana_group",
        )
    with expired_column:
        include_expired = st.checkbox(
            "期限切れも表示",
            key="quest_master_include_expired",
        )
    matches = search_quest_master(
        records,
        query=query,
        include_expired=include_expired,
    )
    if kana_group != "すべて":
        matches = [
            record
            for record in matches
            if quest_master_kana_group(record) == kana_group
        ]
    if not matches:
        st.info(
            "条件に合う登録済み降臨がありません。"
            "初回は上のボタンで公開済み降臨をマスターへ登録してください。"
        )
        return

    selected_id = st.selectbox(
        "使用する登録済み降臨",
        options=[record["quest_id"] for record in matches],
        format_func=lambda value: quest_master_label(next(
            record for record in matches if record["quest_id"] == value
        )),
        key="quest_master_selected_id",
    )
    selected = next(
        record for record in records if record["quest_id"] == selected_id
    )
    image_reference_count = len(selected.get("image_references", []))
    st.caption(
        f"画像照合データ：{image_reference_count}件。"
        "完全な切り出しカードを候補確認画面で割り当てると追加されます。"
    )
    date_column, time_column = st.columns(2)
    with date_column:
        game_date = st.date_input(
            "掲載日",
            value=date.today(),
            key="quest_master_schedule_date",
        )
    with time_column:
        start_time = st.time_input(
            "開始時間",
            value=time(12, 0),
            key="quest_master_schedule_start_time",
        )
    st.caption("終了時間は翌日11:59に自動設定します。")
    if st.button(
        "この登録済み降臨を日程へ追加",
        type="primary",
        key="add_schedule_from_quest_master",
    ):
        try:
            addition = schedule_from_master(selected, game_date, start_time)
            merged = merge_unique(schedules, [addition], schedule_identity)
            message = save_admin_json(
                "schedules.json",
                merged,
                save_schedules,
                "Add descent schedule from quest master",
            )
            st.session_state.pop("schedule_editor", None)
            st.session_state["admin_flash_success"] = (
                f"{message} {addition['date']} {addition['start_time']}の"
                f"{addition['name']}を追加しました。"
            )
            st.rerun()
        except (GitHubStorageError, ValueError) as error:
            st.error(str(error))

    with st.expander("選択中マスターの詳細設定", expanded=False):
        detail_name = st.text_input(
            "名前",
            value=selected.get("name", ""),
            key=f"master_name_{selected_id}",
        )
        detail_name_reading = st.text_input(
            "読み（任意）",
            value=selected.get("name_reading", ""),
            help="五十音分類は先頭1文字、読み検索は入力した文字列を使用します。",
            key=f"master_name_reading_{selected_id}",
        )
        detail_quest_name = st.text_input(
            "クエスト名（任意）",
            value=selected.get("quest_name", ""),
            key=f"master_quest_name_{selected_id}",
        )
        detail_attribute = st.selectbox(
            "属性",
            options=ATTRIBUTES,
            index=ATTRIBUTES.index(selected.get("attribute"))
            if selected.get("attribute") in ATTRIBUTES else 0,
            key=f"master_attribute_{selected_id}",
        )
        detail_difficulty = st.selectbox(
            "難易度",
            options=DIFFICULTIES,
            index=DIFFICULTIES.index(selected.get("difficulty"))
            if selected.get("difficulty") in DIFFICULTIES else 0,
            key=f"master_difficulty_{selected_id}",
        )
        detail_category = st.selectbox(
            "降臨カテゴリ",
            options=SCHEDULE_CATEGORIES,
            index=SCHEDULE_CATEGORIES.index(selected.get("category"))
            if selected.get("category") in SCHEDULE_CATEGORIES else 0,
            key=f"master_category_{selected_id}",
        )
        detail_group = st.text_input(
            "掲載グループ（任意）",
            value=selected.get("group_name", ""),
            key=f"master_group_{selected_id}",
        )
        limited = detail_category in LIMITED_MASTER_CATEGORIES
        detail_availability = st.selectbox(
            "開催方式",
            options=AVAILABILITY_TYPES,
            index=AVAILABILITY_TYPES.index(
                normalize_availability_type(selected.get("availability_type"))
            ),
            disabled=not limited,
            key=f"master_availability_{selected_id}",
        )
        detail_period_end = st.text_input(
            "期間終了日（YYYY-MM-DD）",
            value=selected.get("period_end_date", "") if limited else "",
            disabled=not limited,
            help="コラボ・期間限定だけで使用します。期限後は削除対象にできます。",
            key=f"master_period_end_{selected_id}",
        )
        detail_source_url = st.text_input(
            "情報源URL（任意）",
            value=selected.get("source_url", ""),
            key=f"master_source_url_{selected_id}",
        )
        if st.button(
            "詳細設定を保存",
            key=f"save_master_details_{selected_id}",
        ):
            errors = []
            if not detail_name.strip():
                errors.append("名前を入力してください。")
            if limited and detail_period_end and not validate_date(
                detail_period_end
            ):
                errors.append("期間終了日はYYYY-MM-DD形式で入力してください。")
            proposed = {
                **selected,
                "name": detail_name,
                "name_reading": detail_name_reading,
                "quest_name": detail_quest_name,
                "attribute": detail_attribute,
                "difficulty": detail_difficulty,
                "category": detail_category,
                "group_name": detail_group,
                "availability_type": (
                    detail_availability if limited else AVAILABILITY_SCHEDULED
                ),
                "period_end_date": detail_period_end if limited else "",
                "source_url": detail_source_url,
                "updated_at": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
            }
            proposed_key = quest_master_key(proposed)
            duplicate = any(
                record["quest_id"] != selected_id
                and quest_master_key(record) == proposed_key
                for record in records
            )
            if duplicate:
                errors.append("同じ名前＋難易度のマスターが既にあります。")
            if errors:
                for error in errors:
                    st.error(error)
            else:
                updated_record = normalize_quest_master_record(proposed)
                updated_records = [
                    updated_record
                    if record["quest_id"] == selected_id else record
                    for record in records
                ]
                try:
                    message = save_quest_master_records(
                        updated_records,
                        "Update quest master details",
                    )
                    st.session_state["admin_flash_success"] = message
                    st.rerun()
                except GitHubStorageError as error:
                    st.error(str(error))

    if st.button(
        "このマスターの削除確認へ",
        key=f"prepare_delete_master_{selected_id}",
    ):
        st.session_state["quest_master_delete_id"] = selected_id
        st.rerun()

    delete_id = st.session_state.get("quest_master_delete_id")
    if delete_id:
        delete_record = next(
            (record for record in records if record["quest_id"] == delete_id),
            None,
        )
        if delete_record is None:
            st.session_state.pop("quest_master_delete_id", None)
        else:
            st.warning(
                f"{quest_master_label(delete_record)}を本当に削除しますか？"
            )
            delete_answer = st.radio(
                "削除確認",
                options=["いいえ", "はい"],
                horizontal=True,
                key=f"confirm_delete_master_{delete_id}",
            )
            if st.button(
                "回答を確定",
                key=f"execute_delete_master_{delete_id}",
            ):
                if delete_answer == "はい":
                    remaining = delete_quest_master(records, {delete_id})
                    try:
                        message = save_quest_master_records(
                            remaining,
                            "Delete quest master after confirmation",
                        )
                        st.session_state.pop("quest_master_delete_id", None)
                        st.session_state["admin_flash_success"] = (
                            f"{message} {delete_record['name']}を削除しました。"
                        )
                        st.rerun()
                    except GitHubStorageError as error:
                        st.error(str(error))
                else:
                    st.session_state.pop("quest_master_delete_id", None)
                    st.info("削除を取り消しました。")


def ensure_candidate_id(candidate, index=0):
    if candidate.get("candidate_id"):
        return str(candidate["candidate_id"])
    source = json.dumps(
        candidate,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    candidate_id = hashlib.sha1(
        f"{index}|{source}".encode("utf-8")
    ).hexdigest()[:20]
    candidate["candidate_id"] = candidate_id
    return candidate_id


def reset_schedule_candidate_editor():
    st.session_state.pop("schedule_candidate_editor", None)


def show_video_extraction_result(result):
    source_kind = st.session_state.get("capture_review_source", "video")
    is_screenshot = source_kind == "screenshot"
    st.markdown(
        "　".join((
            f"**候補 {len(result.candidates)}**",
            f"自動補正 {result.recognized_count}",
            f"画像確認 {result.manual_review_count}",
            f"公開済み重複 {result.published_duplicate_count}",
            f"承認待ち重複 {result.pending_duplicate_count}",
            f"除外 {result.rejected_candidate_count}",
        ))
    )
    st.caption(
        f"確認{'画像' if is_screenshot else 'フレーム'} "
        f"{result.sampled_frame_count}枚／"
        f"{'画像間' if is_screenshot else '動画内'}重複 "
        f"{result.video_duplicate_count}件／"
        f"日付OCR未完成 {result.ocr_error_count}件／"
        f"{'画像' if is_screenshot else '動画'}識別子 "
        f"{result.video_fingerprint[:12]}…"
    )


def clear_video_review_state():
    for key in (
        "video_review_candidates",
        "video_extraction_result",
        "video_review_editor",
        "video_review_select_all",
        "video_review_last_select_all",
        "video_review_preview_index",
        "capture_review_source",
        "admin_candidate_tab_active",
    ):
        st.session_state.pop(key, None)
    for key in list(st.session_state):
        if key.startswith((
            "video_review_save_",
            "video_review_overview_save_",
        )):
            st.session_state.pop(key, None)


def keep_candidate_tab_active():
    """抽出操作による再実行後も抽出タブを先頭表示に保つ。"""
    st.session_state["admin_candidate_tab_active"] = True


def mark_all_video_review_candidates_selected():
    """ウィジェット生成前のコールバックで全候補を保存対象にする。"""
    candidates = st.session_state.get("video_review_candidates", [])
    for index, candidate in enumerate(candidates):
        candidate_id = ensure_candidate_id(candidate, index)
        candidate["_selected_for_save"] = True
        st.session_state[
            f"video_review_overview_save_{candidate_id}"
        ] = True
    st.session_state["video_review_candidates"] = candidates
    st.session_state["admin_candidate_tab_active"] = True


def video_review_candidate_label(candidate, index):
    date_value = candidate.get("date") or "日付未確定"
    name = candidate.get("name") or "名前未確定"
    mode = candidate.get("review_mode", "画像確認")
    return f"{index + 1}. {date_value}｜{name}｜{mode}"


def render_video_review_candidate_overview(candidates):
    """画像マスター割り当てとは分けて、保存対象を一覧選択する。"""
    with st.expander(
        f"抽出候補一覧・承認待ち保存（{len(candidates)}件）",
        expanded=True,
    ):
        st.caption(
            "承認待ちへ保存する候補だけチェックしてください。"
            "画像マスターへの登録とは別に選択できます。"
        )
        st.button(
            "全候補を保存対象にする",
            key="video_review_select_all_button",
            on_click=mark_all_video_review_candidates_selected,
        )
        for index, candidate in enumerate(candidates):
            candidate_id = ensure_candidate_id(candidate, index)
            label = (
                f"{index + 1}. {candidate.get('date') or '日付未確定'}｜"
                f"{candidate.get('name') or '名前未確定'}｜"
                f"{candidate.get('attribute') or '属性未確定'}｜"
                f"{candidate.get('difficulty') or '難易度未確定'}｜"
                f"{normalize_schedule_category(candidate.get('category'))}"
            )
            candidate["_selected_for_save"] = st.checkbox(
                label,
                value=bool(candidate.get("_selected_for_save", False)),
                key=f"video_review_overview_save_{candidate_id}",
            )
    st.session_state["video_review_candidates"] = candidates
    return sum(
        bool(candidate.get("_selected_for_save", False))
        for candidate in candidates
    )


def render_video_review_candidates():
    candidates = st.session_state.get("video_review_candidates", [])
    result = st.session_state.get("video_extraction_result")
    if not candidates:
        return

    source_kind = st.session_state.get("capture_review_source", "video")
    source_label = "スクリーンショット" if source_kind == "screenshot" else "動画"
    st.markdown(f"##### {source_label}から取得した一時確認候補")
    st.warning(
        "この段階ではJSONへ保存していません。"
        "確認画像を見て表を修正し、保存対象だけを選んでください。"
    )
    if result is not None:
        show_video_extraction_result(result)

    selected_count = render_video_review_candidate_overview(candidates)
    st.caption(f"承認待ちへの保存対象：{selected_count}/{len(candidates)}件")
    save_column, discard_column = st.columns(2)
    with save_column:
        save_clicked = st.button(
            "選択した候補を承認待ちへ保存",
            type="primary",
            key="save_selected_video_review_candidates",
        )
    with discard_column:
        discard_clicked = st.button(
            "今回の一時候補を破棄",
            key="discard_video_review_candidates",
        )

    if discard_clicked:
        st.session_state["reset_video_review_state"] = True
        st.session_state["admin_flash_success"] = (
            f"{source_label}の一時確認候補を破棄しました。"
            "JSONは変更していません。"
        )
        st.rerun()

    try:
        preview_index = int(
            st.session_state.get("video_review_preview_index", 0)
        )
    except (TypeError, ValueError):
        preview_index = 0
    preview_index = max(0, min(preview_index, len(candidates) - 1))
    st.session_state["video_review_preview_index"] = preview_index
    previous_column, position_column, next_column = st.columns([1, 3, 1])
    with previous_column:
        if st.button(
            "← 前へ",
            disabled=preview_index <= 0,
            key="video_review_previous",
        ):
            st.session_state["video_review_preview_index"] = preview_index - 1
            st.rerun()
    with position_column:
        st.markdown(
            f"**確認中：{preview_index + 1}/{len(candidates)}件**  "
            f"{video_review_candidate_label(candidates[preview_index], preview_index)}"
        )
        st.progress((preview_index + 1) / len(candidates))
    with next_column:
        if st.button(
            "次へ →",
            disabled=preview_index >= len(candidates) - 1,
            key="video_review_next",
        ):
            st.session_state["video_review_preview_index"] = preview_index + 1
            st.rerun()
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

    try:
        all_master_records = normalize_quest_master(
            load_admin_json("quest_master.json", load_quest_master)
        )
        available_master = search_quest_master(
            all_master_records,
            include_expired=False,
        )
    except GitHubStorageError:
        all_master_records = []
        available_master = []
    if available_master:
        learnable, learnable_reason = card_reference_is_learnable(
            preview_candidate
        )
        if learnable:
            st.success(
                "このカードは全体が写っているため、"
                "選択したマスターの画像照合データへ登録できます。"
            )
        else:
            st.warning(
                "このカードは画像マスターへ保存しません："
                f"{learnable_reason} 既存マスターの適用だけは可能です。"
            )
        present_groups = [
            group
            for group in KANA_GROUPS
            if any(
                quest_master_kana_group(record) == group
                for record in available_master
            )
        ]
        review_kana_group = st.selectbox(
            "五十音から絞り込み",
            options=["すべて", *present_groups],
            key=(
                "review_master_kana_"
                f"{ensure_candidate_id(preview_candidate, preview_index)}"
            ),
        )
        filtered_master = available_master
        if review_kana_group != "すべて":
            filtered_master = [
                record
                for record in available_master
                if quest_master_kana_group(record) == review_kana_group
            ]
        selected_master_id = st.selectbox(
            "このカードへ割り当てるマスター",
            options=[record["quest_id"] for record in filtered_master],
            index=None,
            placeholder="名前を入力して検索できます",
            format_func=lambda value: quest_master_label(next(
                    record
                    for record in filtered_master
                    if record["quest_id"] == value
                )),
            key=f"review_master_choice_{ensure_candidate_id(preview_candidate, preview_index)}",
        )
        learn_image_reference = st.checkbox(
            "完全なカードの画像特徴をマスターへ登録する",
            value=learnable,
            disabled=not learnable,
            key=f"learn_review_master_{ensure_candidate_id(preview_candidate, preview_index)}",
        )
        if st.button(
            (
                "マスターを適用して画像特徴を登録"
                if learnable and learn_image_reference
                else "マスターをこの候補へ適用"
            ),
            disabled=not selected_master_id,
            key=f"apply_review_master_{ensure_candidate_id(preview_candidate, preview_index)}",
        ):
            selected_master = next(
                record
                for record in available_master
                if record["quest_id"] == selected_master_id
            )
            learning_message = ""
            reference_added = False
            updated_master_records = all_master_records
            if learnable and learn_image_reference:
                (
                    updated_master_records,
                    reference_added,
                    learning_message,
                ) = add_candidate_image_reference(
                    all_master_records,
                    selected_master_id,
                    preview_candidate,
                )
                if reference_added:
                    try:
                        save_quest_master_records(
                            updated_master_records,
                            "Register card image reference in quest master",
                        )
                    except GitHubStorageError as error:
                        st.error(str(error))
                        return
            for field in (
                "quest_id",
                "name",
                "quest_name",
                "attribute",
                "difficulty",
                "category",
                "group_name",
            ):
                preview_candidate[field] = selected_master.get(field, "")
            preview_candidate["master_match_score"] = 100.0
            preview_candidate["master_match_method"] = "manual_image_assignment"
            preview_candidate["review_mode"] = "マスター選択"
            preview_candidate["ocr_status"] = (
                "マスター手動選択・画像登録済み・要確認"
                if learnable and learn_image_reference
                else "マスター手動選択・要確認"
            )
            candidates[preview_index] = preview_candidate
            if reference_added:
                refreshed_candidates = []
                for candidate in candidates:
                    selected_for_save = candidate.get(
                        "_selected_for_save", False
                    )
                    refreshed, matched = resolve_candidate_with_master(
                        candidate,
                        updated_master_records,
                    )
                    if matched and refreshed.get(
                        "master_match_method"
                    ) == "image":
                        refreshed["_selected_for_save"] = selected_for_save
                        refreshed_candidates.append(refreshed)
                    else:
                        refreshed_candidates.append(candidate)
                candidates = refreshed_candidates
            candidates, duplicate_count = deduplicate_resolved_candidates(
                candidates
            )
            st.session_state["video_review_candidates"] = candidates
            st.session_state["video_review_preview_index"] = min(
                preview_index,
                len(candidates) - 1,
            )
            st.session_state["admin_flash_success"] = (
                f"{selected_master['name']}のマスターを適用しました。"
                + (f" {learning_message}" if learning_message else "")
                + (
                    f"同一日付の重複候補{duplicate_count}件も統合しました。"
                    if duplicate_count else ""
                )
            )
            st.rerun()
    else:
        st.warning(
            "割り当て可能な降臨マスターがありません。"
            "先に「降臨マスター」タブで登録してください。"
        )

    candidate_id = ensure_candidate_id(preview_candidate, preview_index)
    save_current = bool(preview_candidate.get("_selected_for_save", False))

    row = {
        "date": preview_candidate.get("date", ""),
        "name": preview_candidate.get("name", ""),
        "attribute": preview_candidate.get("attribute", ""),
        "difficulty": preview_candidate.get("difficulty", ""),
        "category": normalize_schedule_category(
            preview_candidate.get("category")
        ),
    }
    editor = st.data_editor(
        pd.DataFrame([row]),
        use_container_width=True,
        hide_index=True,
        key=f"video_review_editor_{candidate_id}",
        column_config={
            "attribute": st.column_config.SelectboxColumn(
                "属性", options=[""] + ATTRIBUTES
            ),
            "difficulty": st.column_config.SelectboxColumn(
                "難易度", options=[""] + DIFFICULTIES
            ),
            "category": st.column_config.SelectboxColumn(
                "降臨カテゴリ", options=SCHEDULE_CATEGORIES
            ),
        },
    )

    apply_clicked = st.button(
        "この候補の修正を反映",
        key=f"apply_video_review_{candidate_id}",
    )

    if apply_clicked:
        edited = editor.iloc[0].to_dict()
        for field, value in edited.items():
            preview_candidate[field] = "" if pd.isna(value) else value
        preview_candidate["_selected_for_save"] = save_current
        missing = [
            label
            for field, label in (
                ("date", "日付要修正"),
                ("name", "名前要入力"),
                ("attribute", "属性要確認"),
                ("difficulty", "難易度要確認"),
            )
            if not preview_candidate.get(field)
        ]
        preview_candidate["ocr_status"] = "・".join(
            ["画像確認"] + missing
        )
        st.session_state["video_review_candidates"] = candidates
        st.success("この候補の修正を一時反映しました。")

    if not save_clicked:
        return

    selected_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("_selected_for_save", False)
    ]
    if not selected_candidates:
        st.warning("承認待ちへ保存する候補を選択してください。")
        return

    rows = []
    for index, candidate in enumerate(selected_candidates):
        rows.append({
            "candidate_id": ensure_candidate_id(candidate, index),
            "quest_id": candidate.get("quest_id", ""),
            "year": candidate.get("year"),
            "date": candidate.get("date", ""),
            "start_time": candidate.get("start_time", "12:00"),
            "end_time": candidate.get("end_time", "11:59"),
            "name": candidate.get("name", ""),
            "quest_name": candidate.get("quest_name", ""),
            "attribute": candidate.get("attribute", ""),
            "difficulty": candidate.get("difficulty", ""),
            "category": normalize_schedule_category(candidate.get("category")),
            "group_name": candidate.get("group_name", ""),
            "availability_type": normalize_availability_type(
                candidate.get("availability_type")
            ),
            "period_end_date": candidate.get("period_end_date", ""),
            "source_type": "game",
            "source_url": "",
            "confirmed_at": "",
            "published": False,
        })
    selected_core = pd.DataFrame(rows)
    additions, errors = schedule_rows_from_editor(selected_core)
    if errors:
        for error in errors:
            st.error(error)
        return

    candidate_by_id = {
        ensure_candidate_id(candidate, index): candidate
        for index, candidate in enumerate(candidates)
    }
    selected_records = rows
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
        "portrait_signature",
        "card_complete",
        "card_visible_ratio",
        "card_sharpness",
        "card_completeness_reason",
        "master_match_method",
        "master_match_score",
        "video_fingerprint",
        "screenshot_batch_fingerprint",
        "source_capture_type",
        "fetched_at",
        "review_mode",
        "ocr_mode",
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


def import_schedule_candidates_from_screenshots():
    if st.session_state.pop("reset_video_review_state", False):
        clear_video_review_state()

    st.markdown("#### スクリーンショットから降臨候補を取得")
    st.caption(
        "PNG・JPEGを一度に10枚まで選択できます。"
        "重なって写った同じカードは画像で判定してまとめます。"
        "画像は処理後に保存されず、候補だけを下の確認画面へ渡します。"
        "日程の基準は現在日前後の約1週間から自動判定します。"
    )
    screenshot_reference_date = date.today() - timedelta(days=7)
    uploaded_screenshots = st.file_uploader(
        "モンストアプリのスケジュール画面スクリーンショット",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="schedule_screenshot_uploader",
        on_change=keep_candidate_tab_active,
        help=(
            "縦向きのまま、カード全体と日付が読める画像を選択してください。"
            "隣の画像と1～2枚分重ねても重複候補にはしません。"
        ),
    )

    if st.button(
        "スクリーンショットから降臨候補を抽出",
        type="primary",
        disabled=not uploaded_screenshots,
        key="extract_schedule_screenshots",
        on_click=keep_candidate_tab_active,
    ):
        try:
            screenshot_files = [
                {"name": uploaded.name, "bytes": uploaded.getvalue()}
                for uploaded in uploaded_screenshots
            ]
            published = ensure_schedule_columns(
                load_admin_json("schedules.json", load_schedules)
            )
            pending = load_admin_json("schedule_candidates.json")
            quest_master_records = normalize_quest_master(
                load_admin_json("quest_master.json", load_quest_master)
            )
            progress_bar = st.progress(0.0)
            progress_text = st.empty()

            def update_screenshot_progress(progress, message):
                progress_bar.progress(progress)
                progress_text.caption(message)

            with st.spinner("スクリーンショットを解析しています…"):
                result = extract_screenshot_schedule_candidates(
                    screenshot_files=screenshot_files,
                    year=screenshot_reference_date.year,
                    recording_start_date=screenshot_reference_date,
                    published_schedules=published,
                    pending_candidates=pending,
                    quest_master=quest_master_records,
                    progress_callback=update_screenshot_progress,
                )
            progress_bar.progress(1.0)
            progress_text.caption("スクリーンショット抽出が完了しました。")
            if result.candidates:
                st.session_state["video_review_candidates"] = result.candidates
                st.session_state["video_extraction_result"] = result
                st.session_state["capture_review_source"] = "screenshot"
                st.session_state.pop("video_review_editor", None)
                st.session_state.pop("video_review_select_all", None)
                st.session_state.pop("video_review_last_select_all", None)
                st.success(
                    f"確認画像付きの一時候補{len(result.candidates)}件を"
                    "作成しました。"
                )
            else:
                clear_video_review_state()
                st.info("追加できる新規候補はありませんでした。")
        except (VideoScheduleError, GitHubStorageError) as error:
            st.error(str(error))
        except Exception as error:
            st.error(
                "画像を解析できませんでした。枚数を減らして再度お試しください。"
                f"（詳細：{error}）"
            )


def import_schedule_candidates_from_video():
    if st.session_state.pop("reset_video_review_state", False):
        clear_video_review_state()

    st.markdown("#### 実験機能：アプリ画面録画から降臨候補を取得")
    st.caption(
        "MP4・MOV（100MB以下／3分以内）に対応します。"
        "動画は処理中だけ一時保存し、処理後に削除します。"
        "処理が120秒を超えた場合は安全のため停止します。"
    )
    left, middle, right = st.columns([1, 1.2, 2.8])
    with left:
        recording_start_date = st.date_input(
            "録画内の最初の日程",
            value=date.today(),
            help=(
                "録画で最初に表示されるゲーム日を指定します。"
                "この日から14日を外れたOCR日付は保存しません。"
            ),
        )
    with middle:
        ocr_mode = st.radio(
            "抽出モード",
            [OCR_MODE_FAST, OCR_MODE_PRECISE],
            horizontal=False,
            help=(
                "高速抽出は各カードを原則1回だけ認識します。"
                "精密抽出は不足項目だけ追加認識します。"
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
            progress_bar = st.progress(0.0)
            progress_text = st.empty()

            def update_video_progress(progress, message):
                progress_bar.progress(progress)
                progress_text.caption(message)

            with st.spinner("動画を解析しています…"):
                result = extract_video_schedule_candidates(
                    video_bytes=video_bytes,
                    year=recording_start_date.year,
                    recording_start_date=recording_start_date,
                    published_schedules=published,
                    pending_candidates=pending,
                    ocr_mode=ocr_mode,
                    progress_callback=update_video_progress,
                )
            progress_bar.progress(1.0)
            progress_text.caption(
                f"{ocr_mode}が完了しました。"
            )
            if result.candidates:
                st.session_state["video_review_candidates"] = (
                    result.candidates
                )
                st.session_state["video_extraction_result"] = result
                st.session_state["capture_review_source"] = "video"
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

def review_schedule_candidates():
    candidates = load_admin_json("schedule_candidates.json")
    if not candidates:
        st.info("降臨の自動取得候補はまだありません。")
        return
    st.caption(
        "日常確認に必要な6項目だけを表示しています。"
        "OCR原文・情報源・開催方式などの内部情報は候補データ内に保持します。"
    )

    rows = []
    for index, candidate in enumerate(candidates):
        candidate_id = ensure_candidate_id(candidate, index)
        rows.append({
            "save": False,
            "candidate_id": candidate_id,
            "date": candidate.get("date", ""),
            "name": candidate.get("name", ""),
            "attribute": candidate.get("attribute", ""),
            "difficulty": candidate.get("difficulty", ""),
            "category": normalize_schedule_category(
                candidate.get("category")
            ),
        })

    editor = st.data_editor(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        key="schedule_candidate_editor",
        column_config={
            "save": st.column_config.CheckboxColumn("保存対象"),
            "candidate_id": None,
            "date": st.column_config.TextColumn("日付"),
            "name": st.column_config.TextColumn("名前"),
            "attribute": st.column_config.SelectboxColumn("属性", options=ATTRIBUTES),
            "difficulty": st.column_config.SelectboxColumn("難易度", options=DIFFICULTIES),
            "category": st.column_config.SelectboxColumn(
                "降臨カテゴリ", options=SCHEDULE_CATEGORIES
            ),
        },
    )
    selected = editor[editor["save"] == True]
    if st.button(
        "保存対象を承認・公開してマスターへ登録",
        type="primary",
    ):
        if selected.empty:
            st.warning("承認する候補を選択してください。")
            return
        candidate_lookup = {
            ensure_candidate_id(candidate, index): dict(candidate)
            for index, candidate in enumerate(candidates)
        }
        selected_records = []
        for edited in selected.to_dict("records"):
            candidate_id = str(edited["candidate_id"])
            original = candidate_lookup[candidate_id]
            original.update({
                "candidate_id": candidate_id,
                "date": normalize_text(edited.get("date")),
                "name": normalize_text(edited.get("name")),
                "attribute": normalize_text(edited.get("attribute")),
                "difficulty": normalize_text(edited.get("difficulty")),
                "category": normalize_schedule_category(
                    edited.get("category")
                ),
                "start_time": original.get("start_time") or "12:00",
                "end_time": original.get("end_time") or "11:59",
                "published": True,
            })
            selected_records.append(original)
        additions, errors = schedule_rows_from_editor(
            pd.DataFrame(selected_records)
        )
        if errors:
            for error in errors:
                st.error(error)
            return

        confirmed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        for addition in additions:
            addition["confirmed_at"] = confirmed_at
            addition["source_type"] = "verified"
            addition["published"] = True

        try:
            current_master = normalize_quest_master(
                load_admin_json("quest_master.json", load_quest_master)
            )
            merged_master, added, updated, skipped = upsert_quest_master(
                current_master,
                additions,
            )
            master_by_key = {
                quest_master_key(record): record
                for record in merged_master
            }
            for addition in additions:
                master_record = master_by_key[quest_master_key(addition)]
                addition["quest_id"] = master_record["quest_id"]
            save_quest_master_records(
                merged_master,
                "Register approved candidates in quest master",
            )

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
            st.session_state["admin_flash_success"] = (
                f"{message} マスター追加{added}件・更新{updated}件"
                f"・対象外{skipped}件。"
            )
            st.rerun()
        except GitHubStorageError as error:
            st.error(str(error))

    st.markdown("##### 承認待ち候補の削除")
    candidate_ids = [
        ensure_candidate_id(candidate, index)
        for index, candidate in enumerate(candidates)
    ]
    delete_id = st.selectbox(
        "削除する候補",
        options=[""] + candidate_ids,
        format_func=lambda value: "選択してください" if not value else next(
            (
                f"{candidate.get('date', '')}｜{candidate.get('name', '')}｜"
                f"{candidate.get('difficulty', '')}"
            )
            for index, candidate in enumerate(candidates)
            if ensure_candidate_id(candidate, index) == value
        ),
        key="schedule_candidate_delete_id",
    )
    if st.button(
        "この候補の削除確認へ",
        disabled=not delete_id,
        key="prepare_schedule_candidate_delete",
    ):
        st.session_state["schedule_candidate_delete_confirm_id"] = delete_id
        st.rerun()

    confirm_id = st.session_state.get("schedule_candidate_delete_confirm_id")
    if confirm_id:
        st.warning("選択した承認待ち候補を本当に削除しますか？")
        answer = st.radio(
            "削除確認",
            options=["いいえ", "はい"],
            horizontal=True,
            key=f"confirm_schedule_candidate_delete_{confirm_id}",
        )
        if st.button(
            "回答を確定",
            key=f"execute_schedule_candidate_delete_{confirm_id}",
        ):
            if answer == "はい":
                remaining = [
                    candidate
                    for index, candidate in enumerate(candidates)
                    if ensure_candidate_id(candidate, index) != confirm_id
                ]
                try:
                    message = save_schedule_candidates(remaining)
                    st.session_state.pop(
                        "schedule_candidate_delete_confirm_id", None
                    )
                    st.session_state.pop("schedule_candidate_editor", None)
                    st.session_state["admin_flash_success"] = (
                        f"{message} 承認待ち候補を1件削除しました。"
                    )
                    st.rerun()
                except GitHubStorageError as error:
                    st.error(str(error))
            else:
                st.session_state.pop(
                    "schedule_candidate_delete_confirm_id", None
                )
                st.info("削除を取り消しました。")


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

forced_admin_tab = st.session_state.pop("admin_force_default_tab", "")
candidate_tab_active = bool(
    st.session_state.get("admin_candidate_tab_active")
    or st.session_state.get("video_review_candidates")
)
tab_labels = [
    "降臨マスター",
    "降臨日程",
    "イベント管理",
    "自動取得候補・失敗ログ",
]
master_tab, schedule_tab, event_tab, candidate_tab = st.tabs(
    tab_labels,
    default=(
        forced_admin_tab
        or (
            "自動取得候補・失敗ログ"
            if candidate_tab_active else "降臨マスター"
        )
    ),
)


with master_tab:
    render_quest_master_management()


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
            "quest_id": None,
            "end_next_day": None,
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
                current_master = normalize_quest_master(
                    load_admin_json("quest_master.json", load_quest_master)
                )
                merged_master, added, updated, skipped = upsert_quest_master(
                    current_master,
                    schedule_rows,
                )
                master_by_key = {
                    quest_master_key(record): record
                    for record in merged_master
                }
                for schedule in schedule_rows:
                    master_record = master_by_key.get(
                        quest_master_key(schedule)
                    )
                    if master_record:
                        schedule["quest_id"] = master_record["quest_id"]
                save_quest_master_records(
                    merged_master,
                    "Sync manually edited schedules to quest master",
                )
                message = save_admin_json(
                    "schedules.json",
                    schedule_rows,
                    save_schedules,
                    "Update descent schedules from admin",
                )
                st.success(
                    f"{message} マスター追加{added}件・更新{updated}件"
                    f"・対象外{skipped}件。"
                )
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
    import_schedule_candidates_from_screenshots()
    render_video_review_candidates()
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

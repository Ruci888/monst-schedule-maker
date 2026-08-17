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
    save_schedules,
)
from auto_updater import run_update
from github_storage import (
    GitHubStorageError,
    is_configured as github_is_configured,
    load_remote_json,
    save_remote_json,
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
SCHEDULE_CATEGORIES = ["event", "high_difficulty"]
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

        rows.append({
            "name": name,
            "short_name": short_name,
            "category": category,
            "start_date": start_date,
            "end_date": end_date,
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
        "source_type": "manual",
        "source_url": "",
        "confirmed_at": "",
        "published": True,
    }
    return [{**defaults, **schedule} for schedule in schedules]


def ensure_event_columns(events):
    defaults = {
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


def review_schedule_candidates():
    candidates = load_admin_json("schedule_candidates.json")
    if not candidates:
        st.info("降臨の自動取得候補はまだありません。")
        return

    rows = []
    for candidate in candidates:
        rows.append({
            "approve": False,
            "year": candidate.get("year"),
            "date": candidate.get("date", ""),
            "start_time": candidate.get("start_time", ""),
            "end_time": candidate.get("end_time", ""),
            "name": candidate.get("name", ""),
            "quest_name": candidate.get("quest_name", ""),
            "attribute": candidate.get("attribute", ""),
            "difficulty": candidate.get("difficulty", ""),
            "category": candidate.get("category", "high_difficulty"),
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
        key="schedule_candidate_editor",
        column_config={
            "approve": st.column_config.CheckboxColumn("承認"),
            "attribute": st.column_config.SelectboxColumn("属性", options=ATTRIBUTES),
            "difficulty": st.column_config.SelectboxColumn("難易度", options=DIFFICULTIES),
            "category": st.column_config.SelectboxColumn(
                "カテゴリ", options=SCHEDULE_CATEGORIES
            ),
            "source_url": st.column_config.LinkColumn("公式記事"),
            "review_reason": st.column_config.TextColumn(
                "確認理由", disabled=True
            ),
        },
    )
    selected = editor[editor["approve"] == True].drop(columns=["approve"])
    if st.button("選択した降臨候補を承認・公開", type="primary"):
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
        st.success(message)


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
        st.success(message)


st.title("モンスト スケジュール管理")
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
                    f"終了済み除外 {result['expired_event_count']}件、"
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

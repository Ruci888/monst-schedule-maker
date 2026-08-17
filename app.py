from datetime import date, datetime, timedelta

import streamlit as st

from data_manager import load_events, load_schedules
from event_image_generator import generate_event_image
from image_generator import generate_schedule_image


APP_VERSION = "v1.1.0-beta.3"


st.set_page_config(
    page_title="モンスト スケジュールメーカー",
    page_icon="📅",
    layout="centered",
)


def parse_schedule_datetime(schedule):
    value = (
        f"{schedule['year']}/{schedule['date']} "
        f"{schedule['start_time']}"
    )
    return datetime.strptime(value, "%Y/%m/%d %H:%M")


def parse_event_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def schedule_label(schedule):
    quest_text = (
        f"｜クエスト：{schedule['quest_name']}"
        if schedule.get("quest_name")
        else ""
    )
    return (
        f"{schedule['date']} {schedule['start_time']}～{schedule['end_time']}｜"
        f"{schedule['name']}{quest_text}｜"
        f"{schedule['attribute']}｜{schedule['difficulty']}"
    )


def event_label(event):
    start_date = parse_event_date(event["start_date"])
    end_date = parse_event_date(event["end_date"])
    return (
        f"{start_date.month}/{start_date.day}～{end_date.month}/{end_date.day}｜"
        f"{event['name']}｜{event['category']}"
    )


EVENT_CATEGORY_LABELS = {
    "定期コンテンツ": "定期コンテンツ",
    "コラボ・期間限定": "コラボ・期間限定",
    "コラボガチャ": "コラボガチャ",
    "コラボミッション": "コラボミッション",
    "ガチャ": "ガチャ",
    "育成キャンペーン": "育成キャンペーン",
    "ゲーム内キャンペーン": "ゲーム内CP",
    "マルチキャンペーン": "マルチCP",
    "ミッション": "ミッション",
    "周年CP": "周年CP",
    "獣神化情報": "獣神化情報",
}


EVENT_CATEGORY_ORDER = list(EVENT_CATEGORY_LABELS)


def event_category_sort_key(category):
    try:
        return EVENT_CATEGORY_ORDER.index(category)
    except ValueError:
        return len(EVENT_CATEGORY_ORDER)


def event_key(event):
    return "\x1f".join([
        event.get("name", ""),
        event.get("category", ""),
        event.get("start_date", ""),
        event.get("end_date", ""),
        event.get("source_url", ""),
    ])


def event_adjustment_label(event):
    start_date = parse_event_date(event["start_date"])
    end_date = parse_event_date(event["end_date"])
    name = event.get("short_name") or event["name"]
    period = f"{start_date.month}/{start_date.day}～{end_date.month}/{end_date.day}"
    return f"{name}（{period}）"


def latest_confirmation(items):
    values = [
        item.get("confirmed_at", "")
        for item in items
        if item.get("confirmed_at")
    ]
    if not values:
        return None
    try:
        latest = max(datetime.fromisoformat(value) for value in values)
        return latest.strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return None


def render_schedule_preview(selected_schedules):
    event_schedules = []
    high_difficulty_schedules = []

    for schedule in selected_schedules:
        category = schedule.get("category", "high_difficulty")
        if category == "event":
            event_schedules.append(schedule)
        elif category == "high_difficulty":
            high_difficulty_schedules.append(schedule)

    event_column, high_column = st.columns(2)

    with event_column:
        st.markdown("#### イベント・期間限定")
        if not event_schedules:
            st.caption("選択なし")
        for schedule in event_schedules:
            quest_text = (
                f"｜{schedule['quest_name']}"
                if schedule.get("quest_name")
                else ""
            )
            st.write(
                f"{schedule['date']} {schedule['start_time']}～{schedule['end_time']}｜"
                f"{schedule['name']}{quest_text}｜{schedule['difficulty']}"
            )

    with high_column:
        st.markdown("#### 高難易度降臨")
        if not high_difficulty_schedules:
            st.caption("選択なし")
        for schedule in high_difficulty_schedules:
            quest_text = (
                f"｜{schedule['quest_name']}"
                if schedule.get("quest_name")
                else ""
            )
            st.write(
                f"{schedule['date']} {schedule['start_time']}～{schedule['end_time']}｜"
                f"{schedule['name']}{quest_text}｜{schedule['difficulty']}"
            )


st.title("モンスト スケジュールメーカー")
st.caption(
    "予定を選ぶだけで、スマホ向けのスケジュール画像を生成できます。"
    f"　｜　{APP_VERSION}"
)

schedule_tab, event_tab = st.tabs([
    "降臨スケジュール",
    "イベントスケジュール",
])


with schedule_tab:
    schedules = [
        schedule
        for schedule in load_schedules()
        if schedule.get("published", True)
    ]

    if not schedules:
        st.error("降臨データを読み込めませんでした。")
    else:
        confirmed_at = latest_confirmation(schedules)
        if confirmed_at:
            st.caption(f"掲載データ最終確認：{confirmed_at}")

        selected_schedule_indexes = st.multiselect(
            "掲載する降臨",
            options=range(len(schedules)),
            default=range(len(schedules)),
            format_func=lambda index: schedule_label(schedules[index]),
        )

        selected_schedules = [
            schedules[index]
            for index in selected_schedule_indexes
        ]

        schedule_design = st.selectbox(
            "デザイン",
            options=["ブルー", "ダーク", "シンプル"],
            key="schedule_design",
        )

        if st.button("降臨スケジュールを生成", type="primary"):
            if not selected_schedules:
                st.warning("予定を1つ以上選択してください。")
            else:
                selected_schedules.sort(key=parse_schedule_datetime)
                st.subheader("生成結果")
                render_schedule_preview(selected_schedules)

                schedule_image = generate_schedule_image(
                    selected_schedules,
                    schedule_design,
                )

                st.image(schedule_image, caption="生成した降臨スケジュール")
                st.download_button(
                    label="PNG画像を保存",
                    data=schedule_image.getvalue(),
                    file_name="monst_descent_schedule.png",
                    mime="image/png",
                )


with event_tab:
    events = [event for event in load_events() if event.get("published", True)]
    confirmed_at = latest_confirmation(events)
    if confirmed_at:
        st.caption(f"掲載データ最終確認：{confirmed_at}")

    start_date = st.date_input(
        "表示開始日（14日間）",
        value=date.today(),
        key="event_start_date",
    )
    end_date = start_date + timedelta(days=13)

    available_events = []
    for event in events:
        event_start = parse_event_date(event["start_date"])
        event_end = parse_event_date(event["end_date"])
        if event_start <= end_date and event_end >= start_date:
            available_events.append(event)

    if not events:
        st.error("イベントデータを読み込めませんでした。")
    elif not available_events:
        st.info("選択した14日間に掲載できるイベントはありません。")
    else:
        available_categories = sorted(
            {event["category"] for event in available_events},
            key=event_category_sort_key,
        )

        selected_categories = st.pills(
            "掲載カテゴリ",
            options=available_categories,
            default=available_categories,
            selection_mode="multi",
            format_func=lambda category: EVENT_CATEGORY_LABELS.get(
                category,
                category,
            ),
            key=f"event_categories_{start_date.isoformat()}",
        )

        category_events = [
            event
            for event in available_events
            if event["category"] in (selected_categories or [])
        ]
        event_map = {event_key(event): event for event in category_events}
        valid_event_keys = set(event_map)

        excluded_state_key = f"event_excluded_{start_date.isoformat()}"
        if excluded_state_key in st.session_state:
            st.session_state[excluded_state_key] = [
                key
                for key in st.session_state[excluded_state_key]
                if key in valid_event_keys
            ]

        with st.expander("個別に掲載から外す", expanded=False):
            st.caption("カテゴリ内の一部だけ掲載しない場合に選択してください。")
            excluded_event_keys = st.multiselect(
                "掲載しないイベント",
                options=list(event_map),
                default=[],
                format_func=lambda key: event_adjustment_label(event_map[key]),
                key=excluded_state_key,
                placeholder="除外するイベントを選択",
            )

        selected_events = [
            event
            for key, event in event_map.items()
            if key not in excluded_event_keys
        ]

        st.caption(
            f"選択中：{len(selected_events)}件／"
            f"この期間の掲載候補：{len(available_events)}件"
        )

        event_design = st.radio(
            "デザイン",
            options=["ブルー", "ダーク", "シンプル"],
            horizontal=True,
            key="event_design",
        )

        if st.button("イベントスケジュールを生成", type="primary"):
            if not selected_events:
                st.warning("イベントを1つ以上選択してください。")
            else:
                event_image = generate_event_image(
                    selected_events,
                    event_design,
                    start_date,
                )
                st.image(event_image, caption="生成したイベントスケジュール")
                st.download_button(
                    label="PNG画像を保存",
                    data=event_image.getvalue(),
                    file_name="monst_event_schedule.png",
                    mime="image/png",
                )

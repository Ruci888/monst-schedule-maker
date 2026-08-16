from datetime import date, datetime, timedelta

import streamlit as st

from data_manager import load_events, load_schedules
from event_image_generator import generate_event_image
from image_generator import generate_schedule_image


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
    return (
        f"{schedule['date']} {schedule['start_time']}～{schedule['end_time']}｜"
        f"{schedule['name']}｜{schedule['attribute']}｜{schedule['difficulty']}"
    )


def event_label(event):
    start_date = parse_event_date(event["start_date"])
    end_date = parse_event_date(event["end_date"])
    return (
        f"{start_date.month}/{start_date.day}～{end_date.month}/{end_date.day}｜"
        f"{event['name']}｜{event['category']}"
    )


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
            st.write(
                f"{schedule['date']} {schedule['start_time']}～{schedule['end_time']}｜"
                f"{schedule['name']}｜{schedule['difficulty']}"
            )

    with high_column:
        st.markdown("#### 高難易度降臨")
        if not high_difficulty_schedules:
            st.caption("選択なし")
        for schedule in high_difficulty_schedules:
            st.write(
                f"{schedule['date']} {schedule['start_time']}～{schedule['end_time']}｜"
                f"{schedule['name']}｜{schedule['difficulty']}"
            )


st.title("モンスト スケジュールメーカー")
st.caption("予定を選ぶだけで、スマホ向けのスケジュール画像を生成できます。")

st.info(
    "このアプリは非公式のファンツールです。"
    "株式会社MIXIおよび「モンスターストライク」とは関係ありません。"
)

st.warning(
    "現在の掲載情報は開発用サンプルです。"
    "実際の開催内容は公式サイト・ゲーム内情報をご確認ください。"
)

schedule_tab, event_tab = st.tabs([
    "降臨スケジュール",
    "イベントスケジュール",
])


with schedule_tab:
    schedules = load_schedules()

    if not schedules:
        st.error("降臨データを読み込めませんでした。")
    else:
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
        selected_event_indexes = st.multiselect(
            "掲載するイベント",
            options=range(len(available_events)),
            default=range(len(available_events)),
            format_func=lambda index: event_label(available_events[index]),
        )


        selected_events = [
            available_events[index]
            for index in selected_event_indexes
        ]

        event_design = st.selectbox(
            "デザイン",
            options=["ブルー", "ダーク", "シンプル"],
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

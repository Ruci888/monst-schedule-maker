import base64
from datetime import date, datetime, timedelta

import streamlit as st
import streamlit.components.v1 as components

from data_manager import load_events, load_schedules
from event_image_generator import generate_event_image
from image_generator import generate_schedule_image
from feedback_storage import add_feedback, is_configured as feedback_is_configured
from schedule_utils import (
    CATEGORY_COLLABORATION,
    CATEGORY_FEATURED,
    CATEGORY_LIMITED_EVENT,
    normalize_schedule_category,
    schedule_overlaps_game_days,
    schedule_period_text,
    schedule_start_datetime,
)


APP_VERSION = "v1.1.0-beta.9.22"

SCHEDULE_MODE_FEATURED = "注目"
SCHEDULE_MODE_NORMAL = "通常降臨・爆絶以下"

FEATURED_DIFFICULTIES = [
    "黎絶",
    "轟絶",
    "超究極",
    "超究極・兵",
]

NORMAL_DIFFICULTIES = [
    "爆絶",
    "超絶・廻",
    "超絶",
    "激究極",
    "究極",
    "極",
    "星5制限",
]


st.set_page_config(
    page_title="モンスト スケジュールメーカー",
    page_icon="📅",
    layout="centered",
)

# Keep pill selectors on one horizontal line; narrow screens can scroll sideways.
st.markdown(
    """
    <style>
    [data-testid="stPills"] [role="listbox"] {
        flex-wrap: nowrap !important;
        overflow-x: auto !important;
        scrollbar-width: thin;
    }
    [data-testid="stPills"] [role="option"] {
        flex: 0 0 auto !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def parse_schedule_datetime(schedule):
    return schedule_start_datetime(schedule)


def parse_event_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def schedule_label(schedule):
    quest_text = (
        f"｜クエスト：{schedule['quest_name']}"
        if schedule.get("quest_name")
        else ""
    )


SCHEDULE_DIFFICULTY_ORDER = [
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


def schedule_key(schedule):
    return "\x1f".join([
        str(schedule.get("year", "")),
        schedule.get("date", ""),
        schedule.get("start_time", ""),
        schedule.get("end_time", ""),
        schedule.get("name", ""),
        schedule.get("difficulty", ""),
    ])


def schedule_group_name(schedule):
    return schedule.get("group_name") or "イベント・期間限定"


def schedule_selection_key(schedule):
    category = normalize_schedule_category(schedule.get("category"))
    if category in (CATEGORY_COLLABORATION, CATEGORY_LIMITED_EVENT):
        return f"category:{category}"
    return f"difficulty:{schedule.get('difficulty', 'その他')}"


def schedule_selection_label(selection_key):
    return selection_key.split(":", 1)[-1]


def schedule_selection_sort_key(selection_key):
    kind, label = selection_key.split(":", 1)
    if kind == "category":
        category_order = [CATEGORY_COLLABORATION, CATEGORY_LIMITED_EVENT]
        return (0, category_order.index(label))
    try:
        return (1, SCHEDULE_DIFFICULTY_ORDER.index(label))
    except ValueError:
        return (1, len(SCHEDULE_DIFFICULTY_ORDER))


def schedule_adjustment_label(schedule):
    group_text = ""
    if (
        normalize_schedule_category(schedule.get("category"))
        in (CATEGORY_COLLABORATION, CATEGORY_LIMITED_EVENT)
        and schedule.get("group_name")
    ):
        group_text = f"｜{schedule_group_name(schedule)}"
    return (
        f"{schedule_period_text(schedule)}｜"
        f"{schedule['name']}｜{schedule['difficulty']}{group_text}"
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
    "定期コンテンツ": "定期",
    "コラボ": "コラボ",
    "ガチャ": "ガチャ",
    "ゲーム内キャンペーン": "ゲーム内CP",
    "イベント": "イベント",
    "ミッション": "ミッション",
    "その他": "その他",
}

EVENT_CATEGORY_ORDER = list(EVENT_CATEGORY_LABELS)
PUBLIC_EVENT_GROUPS = list(EVENT_CATEGORY_LABELS.values())

# Legacy categories are only translated for public display so existing JSON keeps working.
def public_event_group(category):
    if category == "定期コンテンツ":
        return "定期"
    if category in {"コラボ", "コラボ・期間限定"}:
        return "コラボ"
    if category == "ガチャ":
        return "ガチャ"
    if category == "ゲーム内キャンペーン":
        return "ゲーム内CP"
    if category == "イベント":
        return "イベント"
    if category == "ミッション":
        return "ミッション"
    if category == "その他":
        return "その他"
    # Removed legacy categories are not exposed as public filter categories.
    return None


def _event_pills_changed(state_key, groups):
    options = ["すべて", *groups]
    current = list(st.session_state.get(state_key, []))
    previous = list(st.session_state.get(f"{state_key}_previous", options))

    # First individual operation from all-selected isolates the operated category.
    if set(previous) == set(options) and set(current) != set(options):
        removed = [item for item in options if item not in current]
        if len(removed) == 1 and removed[0] != "すべて":
            current = [removed[0]]
        elif "すべて" not in current:
            current = groups.copy()
    elif "すべて" in current and "すべて" not in previous:
        current = options.copy()
    else:
        selected = [item for item in current if item != "すべて"]
        if len(selected) == len(groups):
            current = options.copy()
        else:
            current = selected

    st.session_state[state_key] = current
    st.session_state[f"{state_key}_previous"] = current.copy()



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


def render_image_save_actions(image_buffer, file_name, caption):
    """画像を表示し、スマホ向け保存と通常ダウンロードを用意する。"""
    image_bytes = image_buffer.getvalue()
    st.image(image_bytes, caption=caption)

    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    components.html(
        f"""
        <button id="share-image" type="button">写真・フォトに保存</button>
        <p id="save-guide">
          iPhoneは共有画面で「画像を保存」、Androidは「フォト」を選択してください。
        </p>
        <script>
          const button = document.getElementById("share-image");
          const guide = document.getElementById("save-guide");
          const encoded = "{encoded_image}";
          const binary = atob(encoded);
          const bytes = new Uint8Array(binary.length);
          for (let index = 0; index < binary.length; index += 1) {{
            bytes[index] = binary.charCodeAt(index);
          }}
          const blob = new Blob([bytes], {{ type: "image/png" }});
          const file = new File([blob], "{file_name}", {{ type: "image/png" }});

          button.addEventListener("click", async () => {{
            try {{
              if (navigator.share && (!navigator.canShare || navigator.canShare({{ files: [file] }}))) {{
                await navigator.share({{ files: [file] }});
                return;
              }}
            }} catch (error) {{
              if (error.name === "AbortError") return;
            }}

            const imageUrl = URL.createObjectURL(blob);
            const opened = window.open(imageUrl, "_blank");
            if (opened) {{
              guide.textContent = "画像を長押しして、写真またはフォトへ保存してください。";
            }} else {{
              guide.textContent = "下の「PNGファイルとして保存」を使用してください。";
            }}
            window.setTimeout(() => URL.revokeObjectURL(imageUrl), 60000);
          }});
        </script>
        <style>
          body {{ margin: 0; font-family: sans-serif; color: #475569; }}
          #share-image {{
            width: 100%; min-height: 48px; padding: 10px 16px;
            border: 0; border-radius: 8px; cursor: pointer;
            background: #ff4b4b; color: white; font-size: 16px;
            font-weight: 600;
          }}
          #save-guide {{ margin: 8px 2px 0; font-size: 13px; line-height: 1.5; }}
        </style>
        """,
        height=92,
    )

    st.download_button(
        label="PNGファイルとして保存",
        data=image_bytes,
        file_name=file_name,
        mime="image/png",
        on_click="ignore",
        use_container_width=True,
    )


st.title("モンスト スケジュールメーカー")
st.caption(
    "予定を選ぶだけで、スマホ向けのスケジュール画像を生成できます。"
    f"　｜　{APP_VERSION}"
)

event_tab, schedule_tab = st.tabs([
    "イベントスケジュール",
    "降臨スケジュール",
], default="イベントスケジュール")


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

        schedule_start_date = st.date_input(
            "表示開始日（7日間）",
            value=date.today(),
            key="schedule_start_date",
        )
        schedule_end_date = schedule_start_date + timedelta(days=6)

        schedule_mode = st.radio(
            "表示モード",
            options=[SCHEDULE_MODE_FEATURED, SCHEDULE_MODE_NORMAL],
            horizontal=True,
            key="schedule_mode",
        )

        available_schedules = [
            schedule
            for schedule in schedules
            if schedule_overlaps_game_days(
                schedule,
                schedule_start_date,
                schedule_end_date,
            )
        ]

        if not available_schedules:
            st.info("選択した7日間に掲載できる降臨はありません。")
            selected_schedules = []
        else:
            if schedule_mode == SCHEDULE_MODE_FEATURED:
                selected_categories = st.pills(
                    "掲載カテゴリ",
                    options=[CATEGORY_COLLABORATION, CATEGORY_LIMITED_EVENT],
                    default=[CATEGORY_COLLABORATION, CATEGORY_LIMITED_EVENT],
                    selection_mode="multi",
                    key=(
                        "schedule_main_categories_"
                        f"{schedule_start_date.isoformat()}"
                    ),
                )
                difficulty_options = FEATURED_DIFFICULTIES
            else:
                selected_categories = []
                difficulty_options = NORMAL_DIFFICULTIES

            selected_difficulties = st.pills(
                "掲載する難易度",
                options=difficulty_options,
                default=difficulty_options,
                selection_mode="multi",
                key=(
                    f"schedule_difficulties_{schedule_mode}_"
                    f"{schedule_start_date.isoformat()}"
                ),
            )

            selected_category_set = set(selected_categories or [])
            selected_difficulty_set = set(selected_difficulties or [])
            if schedule_mode == SCHEDULE_MODE_FEATURED:
                category_schedules = [
                    schedule
                    for schedule in available_schedules
                    if (
                        normalize_schedule_category(schedule.get("category"))
                        in selected_category_set
                        or (
                            normalize_schedule_category(
                                schedule.get("category")
                            ) == CATEGORY_FEATURED
                            and schedule.get("difficulty")
                            in selected_difficulty_set
                        )
                    )
                ]
            else:
                category_schedules = [
                    schedule
                    for schedule in available_schedules
                    if (
                        normalize_schedule_category(schedule.get("category"))
                        not in (CATEGORY_COLLABORATION, CATEGORY_LIMITED_EVENT)
                        and schedule.get("difficulty")
                        in selected_difficulty_set
                    )
                ]
            schedule_map = {
                schedule_key(schedule): schedule
                for schedule in category_schedules
            }
            valid_schedule_keys = set(schedule_map)
            excluded_state_key = (
                f"schedule_excluded_{schedule_start_date.isoformat()}"
            )
            if excluded_state_key in st.session_state:
                st.session_state[excluded_state_key] = [
                    key
                    for key in st.session_state[excluded_state_key]
                    if key in valid_schedule_keys
                ]

            if schedule_map:
                with st.expander("個別に選択を調整", expanded=False):
                    st.caption(
                        "選択したカテゴリ・難易度の中から、"
                        "掲載しない降臨を指定できます。"
                    )
                    excluded_schedule_keys = st.multiselect(
                        "掲載しない降臨",
                        options=list(schedule_map),
                        default=[],
                        format_func=lambda key: schedule_adjustment_label(
                            schedule_map[key]
                        ),
                        key=excluded_state_key,
                        placeholder="除外する降臨を選択",
                    )
            else:
                excluded_schedule_keys = []
                st.info("掲載したいカテゴリ・難易度を1つ以上選択してください。")

            selected_schedules = [
                schedule
                for key, schedule in schedule_map.items()
                if key not in excluded_schedule_keys
            ]

            st.caption(
                f"選択中：{len(selected_schedules)}件／"
                f"この期間の掲載候補：{len(available_schedules)}件"
            )
        schedule_design = "ブルー"

        if not selected_schedules:
            st.warning("予定を1つ以上選択してください。")
        else:
            selected_schedules.sort(key=parse_schedule_datetime)
            st.subheader("生成結果")
            schedule_image = generate_schedule_image(
                selected_schedules,
                schedule_design,
                schedule_start_date,
                schedule_mode,
            )
            render_image_save_actions(
                schedule_image,
                "monst_descent_schedule.png",
                "生成した降臨スケジュール",
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
        # Always show the full public category set.
        # Filters must not disappear just because the selected 14-day window
        # currently has no event in that category.
        available_groups = PUBLIC_EVENT_GROUPS.copy()
        pills_key = f"event_groups_{start_date.isoformat()}"
        pills_options = ["すべて", *available_groups]
        if pills_key not in st.session_state:
            st.session_state[pills_key] = pills_options.copy()
            st.session_state[f"{pills_key}_previous"] = pills_options.copy()

        selected_pills = st.pills(
            "表示項目選択",
            options=pills_options,
            default=pills_options,
            selection_mode="multi",
            key=pills_key,
            on_change=_event_pills_changed,
            args=(pills_key, available_groups),
        )
        selected_groups = {
            group for group in (selected_pills or [])
            if group != "すべて"
        }

        category_events = [
            event
            for event in available_events
            if public_event_group(event.get("category", "")) in selected_groups
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

        if event_map:
            with st.expander("個別に選択を調整", expanded=False):
                st.caption("選択したカテゴリ内で、掲載しないイベントを指定できます。")
                excluded_event_keys = st.multiselect(
                    "掲載しないイベント",
                    options=list(event_map),
                    default=[],
                    format_func=lambda key: event_adjustment_label(event_map[key]),
                    key=excluded_state_key,
                    placeholder="除外するイベントを選択",
                )
        else:
            excluded_event_keys = []
            st.info("掲載したいカテゴリを1つ以上選択してください。")

        selected_events = [
            event
            for key, event in event_map.items()
            if key not in excluded_event_keys
        ]

        st.caption(
            f"選択中：{len(selected_events)}件／"
            f"この期間の掲載候補：{len(available_events)}件"
        )
        event_design = "ブルー"

        if not selected_events:
            st.warning("イベントを1つ以上選択してください。")
        else:
            event_image = generate_event_image(
                selected_events,
                event_design,
                start_date,
            )
            st.subheader("生成結果")
            render_image_save_actions(
                event_image,
                "monst_event_schedule.png",
                "生成したイベントスケジュール",
            )


st.divider()
st.caption(
    "β版・非公式ファンツールです。公式運営とは関係ありません。"
    "掲載内容は変更・誤りの可能性があるため、最終確認はゲーム内・公式情報をご確認ください。"
)

with st.expander("ご意見・ご要望を送る", expanded=False):
    st.caption("個人情報は入力しないでください。")

    NG_WORDS = [
        "死亡","骨折","重傷","殺害","傷害","暴力","被害者",
        "ポルノ","アダルト","セックス","バイブレーター","マスターベーション",
        "オナニー","スケベ","羞恥","セクロス","エッチ","sex","風俗","童貞",
        "ペニス","巨乳","ロリ","触手","ノーブラ","手ブラ","ローアングル",
        "禁断","tバック","グラビア","美尻","お尻","セクシー","無修正",
        "大麻","麻薬","基地外","糞","死ね","殺す",
    ]

    def normalize_feedback_text(value):
        import unicodedata
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return "".join(ch for ch in normalized if not ch.isspace())

    def contains_ng_word(value):
        normalized = normalize_feedback_text(value)
        return any(normalize_feedback_text(word) in normalized for word in NG_WORDS)

    with st.form("public_feedback_form", clear_on_submit=True):
        feedback_message = st.text_area(
            "ご意見・ご要望",
            max_chars=1000,
            placeholder="使いにくい点や改善してほしい点など",
        )
        feedback_submitted = st.form_submit_button("送信する", use_container_width=True)

    if feedback_submitted:
        from time import time as unix_time
        message = feedback_message.strip()
        last_sent = st.session_state.get("feedback_last_sent_at", 0.0)
        remaining = 60 - int(unix_time() - last_sent)

        if not feedback_is_configured():
            st.error("現在フィードバック機能を利用できません。")
        elif len(message) < 5:
            st.warning("5文字以上で入力してください。")
        elif contains_ng_word(message):
            st.warning("使用できない表現が含まれています。内容を修正してください。")
        elif remaining > 0:
            st.warning(f"連続送信を防ぐため、あと約{remaining}秒お待ちください。")
        else:
            try:
                add_feedback(message)
                st.session_state["feedback_last_sent_at"] = unix_time()
                st.success("ご意見・ご要望を送信しました。ありがとうございます。")
            except Exception:
                st.error("送信に失敗しました。時間をおいてもう一度お試しください。")


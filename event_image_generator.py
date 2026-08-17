from datetime import datetime, timedelta
from io import BytesIO

from PIL import Image, ImageDraw

from image_generator import draw_centered_text, fit_font, get_theme, load_font


CATEGORY_COLORS = {
    "定期コンテンツ": "#2563EB",
    "コラボ・期間限定": "#DC2626",
    "ガチャ": "#D97706",
    "育成キャンペーン": "#059669",
    "ゲーム内キャンペーン": "#0F766E",
    "ミッション": "#DB2777",
    "獣神化情報": "#7C3AED",
    "期限": "#BE123C",
}


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def overlap(event, week_start, week_end):
    return (
        parse_date(event["start_date"]) <= week_end
        and parse_date(event["end_date"]) >= week_start
    )


def draw_week(draw, events, week_start, top, theme):
    left = 35
    right = 1045
    date_header_height = 62
    row_height = 64
    column_width = (right - left) / 7
    week_end = week_start + timedelta(days=6)
    week_events = [event for event in events if overlap(event, week_start, week_end)]

    draw.rounded_rectangle(
        (left, top, right, top + date_header_height),
        radius=14,
        fill=theme["card"],
    )

    weekday_names = "月火水木金土日"
    date_font = load_font(21)
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        cell_left = left + offset * column_width
        cell_right = cell_left + column_width
        day_color = theme["text"]
        if day.weekday() == 5:
            day_color = "#60A5FA"
        elif day.weekday() == 6:
            day_color = "#F87171"

        draw_centered_text(
            draw,
            (cell_left, top, cell_right, top + date_header_height),
            f"{day.month}/{day.day}({weekday_names[day.weekday()]})",
            date_font,
            day_color,
        )
        if offset:
            draw.line(
                (cell_left, top, cell_left, top + date_header_height),
                fill=theme["line"],
                width=2,
            )

    row_top = top + date_header_height + 8
    if not week_events:
        draw_centered_text(
            draw,
            (left, row_top, right, row_top + row_height),
            "掲載イベントなし",
            load_font(22),
            theme["sub_text"],
        )
        return row_top + row_height

    for event in week_events:
        event_start = max(parse_date(event["start_date"]), week_start)
        event_end = min(parse_date(event["end_date"]), week_end)
        start_offset = (event_start - week_start).days
        end_offset = (event_end - week_start).days
        bar_left = left + start_offset * column_width + 4
        bar_right = left + (end_offset + 1) * column_width - 4
        color = CATEGORY_COLORS.get(event["category"], "#475569")

        draw.rounded_rectangle(
            (bar_left, row_top, bar_right, row_top + row_height - 8),
            radius=12,
            fill=color,
        )
        label = event.get("short_name", event["name"])
        label_font = fit_font(
            label,
            maximum_size=21,
            minimum_size=13,
            maximum_width=max(60, bar_right - bar_left - 12),
            draw=draw,
        )
        draw_centered_text(
            draw,
            (bar_left, row_top, bar_right, row_top + row_height - 8),
            label,
            label_font,
            "#FFFFFF",
        )
        row_top += row_height

    return row_top


def generate_event_image(events, design, start_date):
    theme = get_theme(design)
    events = sorted(events, key=lambda event: (event["start_date"], event["name"]))
    second_week = start_date + timedelta(days=7)
    first_count = max(
        1,
        sum(overlap(event, start_date, start_date + timedelta(days=6)) for event in events),
    )
    second_count = max(
        1,
        sum(overlap(event, second_week, second_week + timedelta(days=6)) for event in events),
    )

    width = 1080
    height = max(1350, 300 + (first_count + second_count) * 64 + 230)
    image = Image.new("RGB", (width, height), theme["background"])
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, width, 205), fill=theme["header"])
    draw_centered_text(
        draw,
        (0, 25, width, 125),
        "イベントスケジュール",
        load_font(54),
        theme["text"],
    )
    end_date = start_date + timedelta(days=13)
    period = (
        f"{start_date.year}/{start_date.month}/{start_date.day}～"
        f"{end_date.month}/{end_date.day}"
    )
    draw_centered_text(
        draw,
        (0, 125, width, 190),
        period,
        load_font(27),
        theme["sub_text"],
    )

    first_bottom = draw_week(draw, events, start_date, 235, theme)
    draw_week(draw, events, second_week, first_bottom + 40, theme)

    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    return image_buffer

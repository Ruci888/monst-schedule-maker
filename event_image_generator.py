from datetime import datetime, timedelta
from io import BytesIO

from PIL import Image, ImageDraw

from image_generator import draw_centered_text, fit_font, load_font


CATEGORY_STYLES = {
    "定期コンテンツ": ("#60A5FA", "定期"),
    "コラボ・期間限定": ("#F87171", "コラボ"),
    "コラボガチャ": ("#C084FC", "コラボガチャ"),
    "コラボミッション": ("#F472B6", "コラボミッション"),
    "ガチャ": ("#FBBF24", "ガチャ"),
    "育成キャンペーン": ("#34D399", "育成"),
    "ゲーム内キャンペーン": ("#2DD4BF", "ゲーム内CP"),
    "マルチキャンペーン": ("#2DD4BF", "マルチCP"),
    "ミッション": ("#F472B6", "ミッション"),
    "周年CP": ("#F59E0B", "周年CP"),
    "獣神化情報": ("#A78BFA", "獣神化"),
    "期限": ("#FB7185", "期限"),
}


CATEGORY_ORDER = list(CATEGORY_STYLES)


EVENT_THEMES = {
    "ブルー": {
        "background": "#07152B",
        "header_top": "#061326",
        "header_bottom": "#0B315F",
        "header_text": "#F8FAFC",
        "header_sub_text": "#C7D7EA",
        "surface": "#12233C",
        "surface_alt": "#0E1D33",
        "week_header": "#162B49",
        "text": "#F3F7FC",
        "sub_text": "#AFC0D6",
        "grid": "#314A6D",
        "accent": "#E3B95F",
        "shadow": "#030A14",
    },
    "ダーク": {
        "background": "#0B0F18",
        "header_top": "#03050A",
        "header_bottom": "#161E2E",
        "header_text": "#F9FAFB",
        "header_sub_text": "#C7CDD8",
        "surface": "#1B2230",
        "surface_alt": "#141A25",
        "week_header": "#222B3B",
        "text": "#F9FAFB",
        "sub_text": "#B8C0CE",
        "grid": "#3C4659",
        "accent": "#C9A75B",
        "shadow": "#020307",
    },
    "シンプル": {
        "background": "#E9EEF5",
        "header_top": "#1B304B",
        "header_bottom": "#2E537C",
        "header_text": "#FFFFFF",
        "header_sub_text": "#E1EBF7",
        "surface": "#FFFFFF",
        "surface_alt": "#F5F7FA",
        "week_header": "#DDE5EF",
        "text": "#172033",
        "sub_text": "#5F6B7C",
        "grid": "#BBC7D6",
        "accent": "#B9832F",
        "shadow": "#C8D0DA",
    },
}


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def overlap(event, week_start, week_end):
    return (
        parse_date(event["start_date"]) <= week_end
        and parse_date(event["end_date"]) >= week_start
    )


def category_sort_key(event):
    try:
        category_index = CATEGORY_ORDER.index(event.get("category", ""))
    except ValueError:
        category_index = len(CATEGORY_ORDER)
    return (
        category_index,
        event.get("start_date", ""),
        event.get("end_date", ""),
        event.get("name", ""),
    )


def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, channel)):02X}" for channel in rgb)


def mix_color(first, second, first_ratio=0.5):
    first_rgb = hex_to_rgb(first)
    second_rgb = hex_to_rgb(second)
    return rgb_to_hex(tuple(
        round(first_value * first_ratio + second_value * (1 - first_ratio))
        for first_value, second_value in zip(first_rgb, second_rgb)
    ))


def draw_vertical_gradient(draw, area, top_color, bottom_color):
    left, top, right, bottom = area
    top_rgb = hex_to_rgb(top_color)
    bottom_rgb = hex_to_rgb(bottom_color)
    height = max(1, bottom - top)
    for offset in range(height):
        ratio = offset / max(1, height - 1)
        color = tuple(
            round(start + (end - start) * ratio)
            for start, end in zip(top_rgb, bottom_rgb)
        )
        draw.line((left, top + offset, right, top + offset), fill=color)


def draw_emphasized_centered_text(draw, area, text, font, fill, stroke_fill):
    left, top, right, bottom = area
    box = draw.textbbox((0, 0), text, font=font, stroke_width=1)
    text_width = box[2] - box[0]
    text_height = box[3] - box[1]
    draw.text(
        (
            left + (right - left - text_width) / 2,
            top + (bottom - top - text_height) / 2 - box[1],
        ),
        text,
        font=font,
        fill=fill,
        stroke_width=1,
        stroke_fill=stroke_fill,
    )


def draw_week(draw, events, week_start, top, theme):
    left = 38
    right = 1042
    timeline_left = 365
    date_header_height = 58
    row_height = 52
    column_width = (right - timeline_left) / 7
    week_end = week_start + timedelta(days=6)
    week_events = sorted(
        [event for event in events if overlap(event, week_start, week_end)],
        key=category_sort_key,
    )

    draw.rounded_rectangle(
        (left, top, right, top + date_header_height),
        radius=14,
        fill=theme["week_header"],
    )

    draw_centered_text(
        draw,
        (left, top, timeline_left - 12, top + date_header_height),
        "イベント",
        load_font(20),
        theme["text"],
    )

    weekday_names = "月火水木金土日"
    date_font = load_font(18)
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        cell_left = timeline_left + offset * column_width
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
                fill=theme["grid"],
                width=1,
            )

    draw.line(
        (timeline_left - 12, top, timeline_left - 12, top + date_header_height),
        fill=theme["grid"],
        width=2,
    )

    row_top = top + date_header_height + 8
    if not week_events:
        draw_centered_text(
            draw,
            (left, row_top, right, row_top + row_height),
            "掲載イベントなし",
            load_font(20),
            theme["sub_text"],
        )
        return row_top + row_height

    for row_index, event in enumerate(week_events):
        row_bottom = row_top + row_height - 4
        row_fill = theme["surface"] if row_index % 2 == 0 else theme["surface_alt"]
        draw.rounded_rectangle(
            (left, row_top, right, row_bottom),
            radius=10,
            fill=row_fill,
        )

        category_color, category_label = CATEGORY_STYLES.get(
            event.get("category", ""),
            ("#94A3B8", "その他"),
        )
        badge_left = left + 10
        badge_top = row_top + 12
        badge_width = 86
        badge_bottom = badge_top + 25
        badge_fill = mix_color(category_color, row_fill, 0.27)
        draw.rounded_rectangle(
            (badge_left, badge_top, badge_left + badge_width, badge_bottom),
            radius=8,
            fill=badge_fill,
            outline=mix_color(category_color, row_fill, 0.70),
            width=1,
        )
        badge_font = fit_font(
            category_label,
            maximum_size=13,
            minimum_size=10,
            maximum_width=badge_width - 10,
            draw=draw,
        )
        draw_centered_text(
            draw,
            (badge_left, badge_top, badge_left + badge_width, badge_bottom),
            category_label,
            badge_font,
            category_color,
        )

        label = event.get("short_name") or event["name"]
        label_font = fit_font(
            label,
            maximum_size=20,
            minimum_size=13,
            maximum_width=timeline_left - (badge_left + badge_width) - 34,
            draw=draw,
        )
        draw.text(
            (badge_left + badge_width + 12, row_top + 13),
            label,
            font=label_font,
            fill=theme["text"],
        )

        event_start = max(parse_date(event["start_date"]), week_start)
        event_end = min(parse_date(event["end_date"]), week_end)
        start_offset = (event_start - week_start).days
        end_offset = (event_end - week_start).days
        bar_left = timeline_left + start_offset * column_width + 7
        bar_right = timeline_left + (end_offset + 1) * column_width - 7
        bar_top = row_top + 16
        bar_bottom = row_top + 34

        draw.rounded_rectangle(
            (bar_left + 1, bar_top + 3, bar_right + 1, bar_bottom + 3),
            radius=7,
            fill=theme["shadow"],
        )
        draw.rounded_rectangle(
            (bar_left, bar_top, bar_right, bar_bottom),
            radius=7,
            fill=mix_color(category_color, theme["background"], 0.72),
            outline=mix_color(category_color, "#FFFFFF", 0.82),
            width=1,
        )

        for offset in range(1, 7):
            grid_x = timeline_left + offset * column_width
            draw.line(
                (grid_x, row_top + 7, grid_x, row_bottom - 7),
                fill=theme["grid"],
                width=1,
            )

        row_top += row_height

    return row_top


def generate_event_image(events, design, start_date):
    theme = EVENT_THEMES.get(design, EVENT_THEMES["ブルー"])
    events = sorted(events, key=category_sort_key)
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
    height = max(1350, 275 + (first_count + second_count) * 52 + 215)
    image = Image.new("RGB", (width, height), theme["background"])
    draw = ImageDraw.Draw(image)

    draw_vertical_gradient(
        draw,
        (0, 0, width, 205),
        theme["header_top"],
        theme["header_bottom"],
    )
    draw.rectangle((0, 0, width, 4), fill=theme["accent"])
    draw.rectangle((0, 201, width, 205), fill=theme["accent"])
    draw_emphasized_centered_text(
        draw,
        (0, 25, width, 125),
        "イベントスケジュール",
        load_font(50),
        theme["header_text"],
        theme["header_top"],
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
        load_font(25),
        theme["header_sub_text"],
    )

    first_bottom = draw_week(draw, events, start_date, 230, theme)
    draw_week(draw, events, second_week, first_bottom + 32, theme)

    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    return image_buffer

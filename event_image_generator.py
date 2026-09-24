import re
from datetime import datetime, time, timedelta
from io import BytesIO

from PIL import Image, ImageDraw

from image_generator import draw_centered_text, fit_font, load_font


CATEGORY_STYLES = {
    "定期コンテンツ": ("#60A5FA", "定期"),
    "コラボ": ("#C084FC", "コラボ"),
    "ガチャ": ("#FBBF24", "ガチャ"),
    "ゲーム内キャンペーン": ("#2DD4BF", "ゲーム内CP"),
    "イベント": ("#F87171", "イベント"),
    "ミッション": ("#F472B6", "ミッション"),
    "その他": ("#94A3B8", "その他"),
}

CATEGORY_ORDER = list(CATEGORY_STYLES)
DISPLAY_CATEGORY_STYLES = {
    label: color for color, label in CATEGORY_STYLES.values()
}


def display_category(event):
    category = event.get("category", "")
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
    return "その他"


def display_category_color(event):
    return DISPLAY_CATEGORY_STYLES[display_category(event)]


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
        "sub_text": "#DDE8F5",
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
        "sub_text": "#E5E7EB",
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


def parse_time(value, fallback):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        return fallback


def event_datetimes(event):
    start_date = parse_date(event["start_date"])
    end_date = parse_date(event["end_date"])
    start_value = event.get("start_time", "")
    end_value = event.get("end_time", "")

    start_datetime = datetime.combine(
        start_date,
        parse_time(start_value, time.min),
    )
    if end_value:
        end_datetime = datetime.combine(
            end_date,
            parse_time(end_value, time.max.replace(microsecond=0)),
        )
    else:
        # 時刻がない既存データは終了日いっぱいまで開催として扱う。
        end_datetime = datetime.combine(end_date + timedelta(days=1), time.min)

    if end_datetime < start_datetime:
        end_datetime = start_datetime
    return start_datetime, end_datetime


def overlap(event, week_start, week_end):
    start_datetime, end_datetime = event_datetimes(event)
    week_start_datetime = datetime.combine(week_start, time.min)
    week_end_datetime = datetime.combine(week_end + timedelta(days=1), time.min)
    if start_datetime == end_datetime:
        return week_start_datetime <= start_datetime < week_end_datetime
    return start_datetime < week_end_datetime and end_datetime > week_start_datetime


def display_event_name(event):
    label = event.get("short_name") or event["name"]
    if label.startswith("書庫卵2倍CP"):
        return re.sub(r"\([火水木光闇・]+\)$", "", label)
    return label


def event_time_text(event):
    start_time = event.get("start_time", "")
    end_time = event.get("end_time", "")
    if not start_time and not end_time:
        return "終日"

    start_date = parse_date(event["start_date"])
    end_date = parse_date(event["end_date"])
    start_text = start_time or "0:00"
    end_text = end_time or "23:59"
    if start_date == end_date:
        return f"{start_text}～{end_text}"
    return (
        f"{start_date.month}/{start_date.day} {start_text}～"
        f"{end_date.month}/{end_date.day} {end_text}"
    )


def event_daily_labels(event):
    value = event.get("daily_labels", "")
    start_date = parse_date(event["start_date"])

    if isinstance(value, dict):
        return {
            parse_date(date_value): str(label)
            for date_value, label in value.items()
        }

    if isinstance(value, list):
        labels = [str(label).strip() for label in value if str(label).strip()]
    else:
        labels = [
            label
            for label in re.split(r"[・,、/\s]+", str(value).strip())
            if label
        ]

    # 旧データでは属性順がshort_nameの括弧内に保存されている。
    if not labels:
        short_name = event.get("short_name", "")
        match = re.search(r"書庫卵2倍CP\(([火水木光闇・]+)\)$", short_name)
        if match:
            labels = match.group(1).split("・")

    return {
        start_date + timedelta(days=offset): label
        for offset, label in enumerate(labels)
    }


ATTRIBUTE_COLORS = {
    "火": "#FF4B4B",
    "水": "#48B8FF",
    "木": "#4CD675",
    "光": "#FFD84D",
    "闇": "#D07CFF",
}


def is_library_campaign(event):
    text = f"{event.get('name', '')} {event.get('short_name', '')}"
    return "書庫" in text and ("2倍" in text or "消費0" in text or "消費０" in text)


def bar_time_text(event):
    start_text = event.get("start_time", "") or "0:00"
    end_text = event.get("end_time", "") or "23:59"
    return f"{start_text}～{end_text}"


def category_sort_key(event):
    try:
        category_index = CATEGORY_ORDER.index(event.get("category", ""))
    except ValueError:
        category_index = len(CATEGORY_ORDER)
    return (
        0 if is_library_campaign(event) else 1,
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
    timeline_left = 405
    date_header_height = 58
    row_height = 64
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
        (left + 24, top, timeline_left - 12, top + date_header_height),
        "イベント",
        load_font(20),
        theme["text"],
    )

    weekday_names = "月火水木金土日"
    date_font = load_font(19)
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
            draw.line((cell_left, top, cell_left, top + date_header_height),
                      fill=theme["grid"], width=1)

    draw.line((timeline_left - 12, top, timeline_left - 12, top + date_header_height),
              fill=theme["grid"], width=2)

    row_top = top + date_header_height + 8
    if not week_events:
        draw_centered_text(
            draw, (left, row_top, right, row_top + row_height),
            "掲載イベントなし", load_font(20), theme["sub_text"]
        )
        return row_top + row_height

    for row_index, item in enumerate(week_events):
        row_bottom = row_top + row_height - 4
        row_fill = theme["surface"] if row_index % 2 == 0 else theme["surface_alt"]
        draw.rounded_rectangle((left, row_top, right, row_bottom), radius=10, fill=row_fill)

        category_color = display_category_color(item)

        # Category is represented only by a slim vertical color bar.
        color_bar_left = left + 9
        color_bar_right = color_bar_left + 12
        draw.rectangle(
            (color_bar_left, row_top, color_bar_right, row_top + row_height),
            fill=category_color,
        )

        label = display_event_name(item)
        label_x = color_bar_right + 12
        label_font = fit_font(
            label,
            maximum_size=27,
            minimum_size=15,
            maximum_width=timeline_left - label_x - 24,
            draw=draw,
        )
        box = draw.textbbox((0, 0), label, font=label_font)
        label_h = box[3] - box[1]
        draw.text(
            (label_x, row_top + (row_height - 4 - label_h) / 2 - box[1]),
            label,
            font=label_font,
            fill=theme["text"],
        )

        week_start_datetime = datetime.combine(week_start, time.min)
        week_end_datetime = week_start_datetime + timedelta(days=7)
        event_start, event_end = event_datetimes(item)
        visible_start = max(event_start, week_start_datetime)
        visible_end = min(event_end, week_end_datetime)
        timeline_width = right - timeline_left
        week_seconds = 7 * 24 * 60 * 60
        start_ratio = (visible_start - week_start_datetime).total_seconds() / week_seconds
        end_ratio = (visible_end - week_start_datetime).total_seconds() / week_seconds
        bar_left = timeline_left + start_ratio * timeline_width
        bar_right = timeline_left + end_ratio * timeline_width
        if bar_right - bar_left < 14:
            bar_right = min(right, bar_left + 14)
        bar_top = row_top + 18
        bar_bottom = row_top + 46

        # Draw daily attribute colors for 書庫卵2倍CP; otherwise use category color.
        daily_labels = event_daily_labels(item)
        if daily_labels and display_event_name(item).startswith("書庫卵2倍CP"):
            attribute_colors = {
                "火": "#E61919", "水": "#168FE3", "木": "#16A34A",
                "光": "#E6D500", "闇": "#7119B8",
            }
            for offset in range(7):
                day = week_start + timedelta(days=offset)
                seg_left = max(bar_left, timeline_left + offset * column_width)
                seg_right = min(bar_right, timeline_left + (offset + 1) * column_width)
                if seg_right <= seg_left:
                    continue
                fill = attribute_colors.get(daily_labels.get(day, ""), category_color)
                draw.rectangle((seg_left, bar_top, seg_right, bar_bottom), fill=fill)
            draw.rounded_rectangle(
                (bar_left, bar_top, bar_right, bar_bottom),
                radius=7, outline=mix_color(category_color, "#FFFFFF", 0.82), width=1
            )
        else:
            draw.rounded_rectangle(
                (bar_left + 1, bar_top + 3, bar_right + 1, bar_bottom + 3),
                radius=7, fill=theme["shadow"]
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
            draw.line((grid_x, row_top + 7, grid_x, row_bottom - 7),
                      fill=theme["grid"], width=1)

        # Time: start at left edge, end at right edge, white only, no outline.
        # If the event already started before this displayed week, its original
        # start time is outside the visible range, so do not show that start time.
        event_start_date = parse_date(item["start_date"])
        show_start_time = event_start_date >= week_start
        start_text = item.get("start_time", "") or "0:00"
        end_text = item.get("end_time", "") or "23:59"
        time_font = load_font(17)
        sb = draw.textbbox((0, 0), start_text, font=time_font)
        eb = draw.textbbox((0, 0), end_text, font=time_font)
        sw, ew = sb[2] - sb[0], eb[2] - eb[0]
        cy = (bar_top + bar_bottom) / 2
        available = bar_right - bar_left

        if show_start_time and available >= sw + ew + 20:
            draw.text((bar_left + 6, cy), start_text, font=time_font,
                      fill="#FFFFFF", anchor="lm")
            draw.text((bar_right - 6, cy), end_text, font=time_font,
                      fill="#FFFFFF", anchor="rm")
        elif show_start_time:
            # Short bar fallback: keep labels readable on the dark row background.
            sx = max(timeline_left + 2, bar_left - 6)
            ex = min(right - 2, bar_right + 6)
            draw.text((sx, cy), start_text, font=time_font,
                      fill="#FFFFFF", anchor="rm")
            draw.text((ex, cy), end_text, font=time_font,
                      fill="#FFFFFF", anchor="lm")
        else:
            # The start is before the displayed range; only the end time remains.
            draw.text((bar_right - 6, cy), end_text, font=time_font,
                      fill="#FFFFFF", anchor="rm")

        row_top += row_height

    return row_top

def generate_event_image(events, design="ブルー", start_date=None):
    # Public beta uses one fixed high-contrast design.
    theme = EVENT_THEMES["ブルー"]
    if start_date is None:
        raise ValueError("start_date is required")

    events = sorted(events, key=category_sort_key)
    second_week = start_date + timedelta(days=7)
    first_count = max(1, sum(overlap(e, start_date, start_date + timedelta(days=6)) for e in events))
    second_count = max(1, sum(overlap(e, second_week, second_week + timedelta(days=6)) for e in events))

    width = 1080
    header_height = 270
    height = max(1420, header_height + 70 + (first_count + second_count) * 64 + 215)
    image = Image.new("RGB", (width, height), theme["background"])
    draw = ImageDraw.Draw(image)

    draw_vertical_gradient(draw, (0, 0, width, header_height),
                           theme["header_top"], theme["header_bottom"])
    draw.rectangle((0, 0, width, 4), fill=theme["accent"])
    draw.rectangle((0, header_height - 4, width, header_height), fill=theme["accent"])

    draw_emphasized_centered_text(
        draw, (0, 18, width, 102), "イベントスケジュール",
        load_font(48), theme["header_text"], theme["header_top"]
    )

    # Six public categories in one horizontal legend row.
    legend_items = list(DISPLAY_CATEGORY_STYLES.items())
    legend_font = load_font(19)
    widths = []
    for label, _ in legend_items:
        b = draw.textbbox((0, 0), label, font=legend_font)
        widths.append(14 + 8 + (b[2] - b[0]) + 20)
    total = sum(widths)
    x = (width - total) / 2
    cy = 136
    for (label, color), item_w in zip(legend_items, widths):
        draw.rounded_rectangle((x, cy - 10, x + 14, cy + 10), radius=3, fill=color)
        draw.text((x + 22, cy), label, font=legend_font,
                  fill=theme["header_text"], anchor="lm")
        x += item_w

    end_date = start_date + timedelta(days=13)
    period = f"{start_date.year}/{start_date.month}/{start_date.day}～{end_date.month}/{end_date.day}"
    draw_centered_text(
        draw, (0, 178, width, 228), period,
        load_font(24), theme["header_sub_text"]
    )

    first_bottom = draw_week(draw, events, start_date, header_height + 25, theme)
    draw_week(draw, events, second_week, first_bottom + 32, theme)

    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    return image_buffer


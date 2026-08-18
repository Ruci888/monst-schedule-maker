from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from schedule_utils import (
    CATEGORY_COLLABORATION,
    CATEGORY_FEATURED,
    CATEGORY_LIMITED_EVENT,
    normalize_schedule_category,
    schedule_active_on_game_day,
    schedule_game_day,
    schedule_start_datetime,
    schedule_time_text_for_day,
)


BASE_DIR = Path(__file__).resolve().parent


def load_font(size):
    candidates = [
        BASE_DIR / "fonts" / "ipaexg.ttf",
        Path("C:/Windows/Fonts/meiryo.ttc"),
        Path("C:/Windows/Fonts/YuGothM.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]

    try:
        import japanize_matplotlib

        candidates.insert(
            0,
            Path(japanize_matplotlib.__file__).resolve().parent / "fonts" / "ipaexg.ttf",
        )
    except ImportError:
        pass

    for font_path in candidates:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size)

    return ImageFont.load_default()


def get_theme(design):
    themes = {
        "ブルー": {
            "background": "#071A3D",
            "header": "#0755A5",
            "card": "#202938",
            "text": "#FFFFFF",
            "sub_text": "#D7E8FF",
            "line": "#607089",
        },
        "ダーク": {
            "background": "#111827",
            "header": "#030712",
            "card": "#1F2937",
            "text": "#F9FAFB",
            "sub_text": "#D1D5DB",
            "line": "#607089",
        },
        "シンプル": {
            "background": "#E5E7EB",
            "header": "#374151",
            "card": "#FFFFFF",
            "text": "#111827",
            "sub_text": "#4B5563",
            "line": "#9CA3AF",
        },
    }
    return themes.get(design, themes["ブルー"])


def get_attribute_color(attribute):
    return {
        "火": "#FF4B4B",
        "水": "#48B8FF",
        "木": "#4CD675",
        "光": "#FFD84D",
        "闇": "#D07CFF",
    }.get(attribute, "#FFFFFF")


def get_difficulty_color(difficulty):
    return {
        "黎絶": "#9B1C1C",
        "轟絶": "#163E87",
        "超究極": "#8A3FFC",
        "超究極・兵": "#166534",
        "爆絶": "#B45309",
        "超絶": "#6D28D9",
        "激究極": "#047857",
        "究極": "#475569",
        "星5制限": "#BE123C",
        "極": "#64748B",
    }.get(difficulty, "#4B5563")


def parse_schedule_datetime(schedule):
    return schedule_start_datetime(schedule)


def fit_font(text, maximum_size, minimum_size, maximum_width, draw):
    for size in range(maximum_size, minimum_size - 1, -1):
        font = load_font(size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= maximum_width:
            return font
    return load_font(minimum_size)


def draw_centered_text(draw, area, text, font, fill):
    left, top, right, bottom = area
    box = draw.textbbox((0, 0), text, font=font)
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
    )


def draw_schedule_item(draw, schedule, display_day, x, y, column_right, theme):
    information_font = load_font(20)
    label_font = fit_font(
        schedule["difficulty"], 17, 13, 92, draw
    )

    time_text = schedule_time_text_for_day(schedule, display_day)
    draw.text((x, y), time_text, font=information_font, fill=theme["sub_text"])

    category = normalize_schedule_category(schedule.get("category"))
    category_labels = {
        CATEGORY_COLLABORATION: ("コラボ", "#B91C1C"),
        CATEGORY_LIMITED_EVENT: ("期間限定", "#A16207"),
    }
    category_label = category_labels.get(category)
    if category_label:
        category_text, category_color = category_label
        category_width = 82
        category_height = 28
        category_x = column_right - category_width - 18
        draw.rounded_rectangle(
            (
                category_x,
                y,
                category_x + category_width,
                y + category_height,
            ),
            radius=10,
            fill=category_color,
        )
        draw_centered_text(
            draw,
            (
                category_x,
                y,
                category_x + category_width,
                y + category_height,
            ),
            category_text,
            load_font(14),
            "#FFFFFF",
        )

    label_width = 112
    label_height = 42
    label_x = column_right - label_width - 12
    label_y = y + 32
    name_width = max(80, label_x - x - 12)
    name_font = fit_font(schedule["name"], 28, 18, name_width, draw)

    draw.text(
        (x, y + 34),
        schedule["name"],
        font=name_font,
        fill=get_attribute_color(schedule["attribute"]),
    )
    draw.rounded_rectangle(
        (label_x, label_y, label_x + label_width, label_y + label_height),
        radius=12,
        fill=get_difficulty_color(schedule["difficulty"]),
    )
    draw_centered_text(
        draw,
        (label_x, label_y, label_x + label_width, label_y + label_height),
        schedule["difficulty"],
        label_font,
        "#FFFFFF",
    )


def draw_normal_schedule_item(draw, schedule, x, y, column_right, theme):
    label_width = 94
    label_height = 34
    label_x = column_right - label_width - 10
    name_width = max(70, label_x - x - 10)
    name_font = fit_font(schedule["name"], 25, 16, name_width, draw)
    label_font = fit_font(
        schedule["difficulty"], 15, 11, label_width - 10, draw
    )
    draw.text(
        (x, y + 3),
        schedule["name"],
        font=name_font,
        fill=get_attribute_color(schedule["attribute"]),
    )
    draw.rounded_rectangle(
        (label_x, y, label_x + label_width, y + label_height),
        radius=10,
        fill=get_difficulty_color(schedule["difficulty"]),
    )
    draw_centered_text(
        draw,
        (label_x, y, label_x + label_width, y + label_height),
        schedule["difficulty"],
        label_font,
        "#FFFFFF",
    )


def generate_normal_schedule_image(schedules, design, start_date=None):
    theme = get_theme(design)
    schedules = sorted(schedules, key=parse_schedule_datetime)
    first_day = start_date or schedule_game_day(schedules[0])
    days = [first_day + timedelta(days=offset) for offset in range(7)]
    left_difficulties = {"爆絶", "超絶", "激究極"}
    schedule_by_date = {
        day: {"upper": [], "lower": []}
        for day in days
    }

    for schedule in schedules:
        column_name = (
            "upper"
            if schedule.get("difficulty") in left_difficulties
            else "lower"
        )
        for day in days:
            if schedule_active_on_game_day(schedule, day):
                schedule_by_date[day][column_name].append(schedule)

    row_heights = []
    for date_data in schedule_by_date.values():
        largest_count = max(
            len(date_data["upper"]),
            len(date_data["lower"]),
            1,
        )
        row_heights.append(max(105, 20 + largest_count * 50))

    width = 1080
    header_height = 250
    column_header_height = 72
    content_height = sum(row_heights) + 6 * 10
    height = max(
        1350,
        header_height + column_header_height + content_height + 50,
    )
    image = Image.new("RGB", (width, height), theme["background"])
    draw = ImageDraw.Draw(image)

    left_edge = 30
    date_right = 190
    group_right = 620
    right_edge = 1050

    draw.rectangle((0, 0, width, header_height), fill=theme["header"])
    draw_centered_text(
        draw,
        (0, 25, width, 130),
        "通常降臨スケジュール",
        load_font(54),
        theme["text"],
    )
    period_text = (
        f"{days[0].year}/{days[0].month}/{days[0].day}～"
        f"{days[-1].month}/{days[-1].day}　各日12:00～翌11:59"
    )
    draw_centered_text(
        draw,
        (0, 135, width, 215),
        period_text,
        load_font(25),
        theme["sub_text"],
    )

    heading_top = header_height
    heading_bottom = heading_top + column_header_height
    draw.rounded_rectangle(
        (left_edge, heading_top, right_edge, heading_bottom),
        radius=16,
        fill=theme["card"],
    )
    heading_font = load_font(23)
    draw_centered_text(
        draw,
        (left_edge, heading_top, date_right, heading_bottom),
        "日程",
        heading_font,
        theme["text"],
    )
    draw_centered_text(
        draw,
        (date_right, heading_top, group_right, heading_bottom),
        "爆絶・超絶・激究極",
        heading_font,
        theme["text"],
    )
    draw_centered_text(
        draw,
        (group_right, heading_top, right_edge, heading_bottom),
        "究極・極・星5制限",
        heading_font,
        theme["text"],
    )
    for line_x in (date_right, group_right):
        draw.line(
            (line_x, heading_top, line_x, heading_bottom),
            fill=theme["line"],
            width=3,
        )

    weekday_names = "月火水木金土日"
    y = heading_bottom + 12
    for (day, date_data), row_height in zip(
        schedule_by_date.items(), row_heights
    ):
        draw.rounded_rectangle(
            (left_edge, y, right_edge, y + row_height),
            radius=18,
            fill=theme["card"],
        )
        for line_x in (date_right, group_right):
            draw.line(
                (line_x, y, line_x, y + row_height),
                fill=theme["line"],
                width=3,
            )
        date_text = f"{day.month}/{day.day}\n({weekday_names[day.weekday()]})"
        draw.multiline_text(
            (left_edge + 80, y + row_height / 2),
            date_text,
            font=load_font(32),
            fill=theme["text"],
            anchor="mm",
            align="center",
            spacing=6,
        )

        item_y = y + 13
        for schedule in date_data["upper"]:
            draw_normal_schedule_item(
                draw,
                schedule,
                date_right + 16,
                item_y,
                group_right,
                theme,
            )
            item_y += 50

        item_y = y + 13
        for schedule in date_data["lower"]:
            draw_normal_schedule_item(
                draw,
                schedule,
                group_right + 16,
                item_y,
                right_edge,
                theme,
            )
            item_y += 50

        y += row_height + 10

    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    return image_buffer


def generate_schedule_image(
    schedules,
    design,
    start_date=None,
    schedule_mode="注目",
):
    if schedule_mode == "通常降臨・爆絶以下":
        return generate_normal_schedule_image(
            schedules,
            design,
            start_date,
        )

    theme = get_theme(design)
    schedules = sorted(schedules, key=parse_schedule_datetime)
    first_day = start_date or schedule_game_day(schedules[0])
    days = [first_day + timedelta(days=offset) for offset in range(7)]

    schedule_by_date = {
        day: {"event": [], "high_difficulty": []}
        for day in days
    }

    for schedule in schedules:
        category = normalize_schedule_category(schedule.get("category"))
        column_name = (
            "event"
            if category in (CATEGORY_COLLABORATION, CATEGORY_LIMITED_EVENT)
            else "high_difficulty"
        )
        for day in days:
            if schedule_active_on_game_day(schedule, day):
                schedule_by_date[day][column_name].append(schedule)

    row_heights = []
    for date_data in schedule_by_date.values():
        largest_count = max(
            len(date_data["event"]),
            len(date_data["high_difficulty"]),
            1,
        )
        row_heights.append(max(130, 24 + largest_count * 92))

    width = 1080
    header_height = 250
    column_header_height = 72
    content_height = sum(row_heights) + 6 * 10
    height = max(1350, header_height + column_header_height + content_height + 50)
    image = Image.new("RGB", (width, height), theme["background"])
    draw = ImageDraw.Draw(image)

    left_edge = 30
    date_right = 190
    event_right = 635
    right_edge = 1050

    draw.rectangle((0, 0, width, header_height), fill=theme["header"])
    draw_centered_text(
        draw, (0, 25, width, 130), "降臨スケジュール", load_font(58), theme["text"]
    )
    period_text = (
        f"{days[0].year}/{days[0].month}/{days[0].day}～"
        f"{days[-1].month}/{days[-1].day}　各日12:00～翌11:59"
    )
    draw_centered_text(
        draw, (0, 135, width, 215), period_text, load_font(25), theme["sub_text"]
    )

    heading_top = header_height
    heading_bottom = heading_top + column_header_height
    draw.rounded_rectangle(
        (left_edge, heading_top, right_edge, heading_bottom),
        radius=16,
        fill=theme["card"],
    )

    heading_font = load_font(25)
    draw_centered_text(draw, (left_edge, heading_top, date_right, heading_bottom), "日程", heading_font, theme["text"])
    draw_centered_text(draw, (date_right, heading_top, event_right, heading_bottom), "コラボ・期間限定", heading_font, theme["text"])
    draw_centered_text(draw, (event_right, heading_top, right_edge, heading_bottom), "高難易度・注目", heading_font, theme["text"])

    for line_x in (date_right, event_right):
        draw.line((line_x, heading_top, line_x, heading_bottom), fill=theme["line"], width=3)

    weekday_names = "月火水木金土日"
    y = heading_bottom + 12
    for (day, date_data), row_height in zip(schedule_by_date.items(), row_heights):
        draw.rounded_rectangle(
            (left_edge, y, right_edge, y + row_height),
            radius=18,
            fill=theme["card"],
        )
        for line_x in (date_right, event_right):
            draw.line((line_x, y, line_x, y + row_height), fill=theme["line"], width=3)

        date_text = f"{day.month}/{day.day}\n({weekday_names[day.weekday()]})"
        draw.multiline_text(
            (left_edge + 80, y + row_height / 2),
            date_text,
            font=load_font(34),
            fill=theme["text"],
            anchor="mm",
            align="center",
            spacing=7,
        )

        item_y = y + 15
        for schedule in date_data["event"]:
            draw_schedule_item(draw, schedule, day, date_right + 18, item_y, event_right, theme)
            item_y += 92

        item_y = y + 15
        for schedule in date_data["high_difficulty"]:
            draw_schedule_item(draw, schedule, day, event_right + 18, item_y, right_edge, theme)
            item_y += 92

        y += row_height + 10

    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    return image_buffer

from datetime import datetime, time, timedelta


CATEGORY_COLLABORATION = "コラボ"
CATEGORY_LIMITED_EVENT = "イベント・期間限定"
CATEGORY_FEATURED = "高難易度・注目"

SCHEDULE_CATEGORIES = [
    CATEGORY_COLLABORATION,
    CATEGORY_LIMITED_EVENT,
    CATEGORY_FEATURED,
]

AVAILABILITY_SCHEDULED = "時間指定"
AVAILABILITY_PERIOD = "期間中常設"

AVAILABILITY_TYPES = [
    AVAILABILITY_SCHEDULED,
    AVAILABILITY_PERIOD,
]


def normalize_schedule_category(value):
    aliases = {
        "collaboration": CATEGORY_COLLABORATION,
        "limited_event": CATEGORY_LIMITED_EVENT,
        "event": CATEGORY_LIMITED_EVENT,
        "high_difficulty": CATEGORY_FEATURED,
    }
    return aliases.get(value, value or CATEGORY_FEATURED)


def normalize_availability_type(value):
    aliases = {
        "scheduled": AVAILABILITY_SCHEDULED,
        "period": AVAILABILITY_PERIOD,
    }
    return aliases.get(value, value or AVAILABILITY_SCHEDULED)


def schedule_start_datetime(schedule):
    return datetime.strptime(
        f"{schedule['year']}/{schedule['date']} {schedule['start_time']}",
        "%Y/%m/%d %H:%M",
    )


def schedule_end_datetime(schedule):
    start = schedule_start_datetime(schedule)
    availability_type = normalize_availability_type(
        schedule.get("availability_type")
    )

    if availability_type == AVAILABILITY_PERIOD:
        period_end_date = schedule.get("period_end_date", "")
        if period_end_date:
            return datetime.strptime(
                f"{period_end_date} {schedule['end_time']}",
                "%Y-%m-%d %H:%M",
            )

    end = datetime.combine(
        start.date(),
        datetime.strptime(schedule["end_time"], "%H:%M").time(),
    )
    if end <= start:
        end += timedelta(days=1)
    return end


def game_day_bounds(day):
    start = datetime.combine(day, time(12, 0))
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return start, end


def schedule_game_day(schedule):
    start = schedule_start_datetime(schedule)
    if start.time() < time(12, 0):
        return start.date() - timedelta(days=1)
    return start.date()


def schedule_active_on_game_day(schedule, day):
    availability_type = normalize_availability_type(
        schedule.get("availability_type")
    )
    if availability_type == AVAILABILITY_SCHEDULED:
        return schedule_game_day(schedule) == day

    row_start, row_end = game_day_bounds(day)
    return (
        schedule_start_datetime(schedule) <= row_end
        and schedule_end_datetime(schedule) >= row_start
    )


def schedule_overlaps_game_days(schedule, first_day, last_day):
    availability_type = normalize_availability_type(
        schedule.get("availability_type")
    )
    if availability_type == AVAILABILITY_SCHEDULED:
        return first_day <= schedule_game_day(schedule) <= last_day

    window_start, _ = game_day_bounds(first_day)
    _, window_end = game_day_bounds(last_day)
    return (
        schedule_start_datetime(schedule) <= window_end
        and schedule_end_datetime(schedule) >= window_start
    )


def schedule_period_text(schedule):
    start = schedule_start_datetime(schedule)
    end = schedule_end_datetime(schedule)
    availability_type = normalize_availability_type(
        schedule.get("availability_type")
    )
    if availability_type == AVAILABILITY_PERIOD:
        return (
            f"{start.month}/{start.day} {start.strftime('%H:%M')}～"
            f"{end.month}/{end.day} {end.strftime('%H:%M')}"
        )
    return (
        f"{start.month}/{start.day} "
        f"{start.strftime('%H:%M')}～{end.strftime('%H:%M')}"
    )


def schedule_time_text_for_day(schedule, day):
    availability_type = normalize_availability_type(
        schedule.get("availability_type")
    )
    start = schedule_start_datetime(schedule)
    end = schedule_end_datetime(schedule)

    if availability_type == AVAILABILITY_SCHEDULED:
        return f"{start.strftime('%H:%M')}～{end.strftime('%H:%M')}"

    row_start, row_end = game_day_bounds(day)
    starts_today = row_start <= start <= row_end
    ends_today = row_start <= end <= row_end

    if starts_today and ends_today:
        return f"{start.strftime('%H:%M')}～{end.strftime('%H:%M')}"
    if starts_today:
        return f"{start.strftime('%H:%M')}～期間中"
    if ends_today:
        return f"期間中～{end.strftime('%H:%M')}"
    return "期間中いつでも"

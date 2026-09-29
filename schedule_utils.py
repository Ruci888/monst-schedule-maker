from datetime import datetime, time, timedelta


CATEGORY_COLLABORATION = "コラボ"
CATEGORY_LIMITED_EVENT = "イベント・期間限定"
CATEGORY_FEATURED = "高難易度・注目"
CATEGORY_NORMAL = "通常降臨"

SCHEDULE_CATEGORIES = [
    CATEGORY_COLLABORATION,
    CATEGORY_LIMITED_EVENT,
    CATEGORY_FEATURED,
    CATEGORY_NORMAL,
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
        "normal": CATEGORY_NORMAL,
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
            end = datetime.strptime(
                f"{period_end_date} {schedule['end_time']}",
                "%Y-%m-%d %H:%M",
            )
            # period_end_date は管理画面で指定した「最後に掲載する日」。
            # 終了時刻が正午より前でも翌日へずらさない。
            return end

    end = datetime.combine(
        start.date(),
        datetime.strptime(schedule["end_time"], "%H:%M").time(),
    )
    if schedule.get("end_next_day") or end <= start:
        end += timedelta(days=1)
    return end


def game_day_bounds(day):
    start = datetime.combine(day, time(12, 0))
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return start, end


def schedule_game_day(schedule):
    start = schedule_start_datetime(schedule)
    availability_type = normalize_availability_type(
        schedule.get("availability_type")
    )

    # 時間指定の降臨は、管理画面で入力した date をそのまま掲載日にする。
    # 0:01～11:59 の降臨を前日の欄へ移動させない。
    if availability_type == AVAILABILITY_SCHEDULED:
        return start.date()

    # 期間中常設も管理画面の date をそのまま掲載開始日にする。
    return start.date()


def schedule_active_on_game_day(schedule, day):
    availability_type = normalize_availability_type(
        schedule.get("availability_type")
    )
    if availability_type == AVAILABILITY_SCHEDULED:
        return schedule_game_day(schedule) == day

    start_day = schedule_start_datetime(schedule).date()
    end_day = schedule_end_datetime(schedule).date()
    return start_day <= day <= end_day


def schedule_overlaps_game_days(schedule, first_day, last_day):
    availability_type = normalize_availability_type(
        schedule.get("availability_type")
    )
    if availability_type == AVAILABILITY_SCHEDULED:
        return first_day <= schedule_game_day(schedule) <= last_day

    start_day = schedule_start_datetime(schedule).date()
    end_day = schedule_end_datetime(schedule).date()
    return start_day <= last_day and end_day >= first_day


def schedule_period_text(schedule):
    start = schedule_start_datetime(schedule)
    end = schedule_end_datetime(schedule)
    availability_type = normalize_availability_type(
        schedule.get("availability_type")
    )
    if availability_type == AVAILABILITY_PERIOD:
        last_day = schedule.get("period_end_date", "")
        if last_day:
            last_day_value = datetime.strptime(last_day, "%Y-%m-%d").date()
            return (
                f"{start.month}/{start.day} {start.strftime('%H:%M')}～"
                f"{last_day_value.month}/{last_day_value.day} "
                f"{end.strftime('%H:%M')}終了"
            )
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
    if availability_type == AVAILABILITY_SCHEDULED:
        end = schedule_end_datetime(schedule)
        return f"{start.strftime('%H:%M')}～{end.strftime('%H:%M')}"

    # 期間中常設は、行にキャラ名があるだけで開催中と分かるため、
    # 「期間中」「期間中いつでも」「～11:59」は画像に表示しない。
    # 初日の開始が標準の12:00以外の場合だけ開始時刻を残す。
    if schedule_game_day(schedule) == day and start.time() != time(12, 0):
        return f"{start.strftime('%H:%M')}～"
    return ""

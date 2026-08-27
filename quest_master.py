import hashlib
import unicodedata
from datetime import date, datetime

from schedule_utils import (
    AVAILABILITY_SCHEDULED,
    CATEGORY_COLLABORATION,
    CATEGORY_LIMITED_EVENT,
    normalize_availability_type,
    normalize_schedule_category,
)


LIMITED_MASTER_CATEGORIES = {
    CATEGORY_COLLABORATION,
    CATEGORY_LIMITED_EVENT,
}


def normalize_master_name(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    return "".join(text.split()).casefold()


def quest_master_key(record):
    return (
        normalize_master_name(record.get("name")),
        unicodedata.normalize(
            "NFKC", str(record.get("difficulty", ""))
        ).strip(),
    )


def make_quest_id(record):
    name, difficulty = quest_master_key(record)
    digest = hashlib.sha1(
        f"{name}\x1f{difficulty}".encode("utf-8")
    ).hexdigest()[:16]
    return f"quest_{digest}"


def _timestamp(now=None):
    value = now or datetime.now().astimezone()
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time()).astimezone()
    return value.isoformat(timespec="seconds")


def is_limited_master(record):
    return normalize_schedule_category(
        record.get("category")
    ) in LIMITED_MASTER_CATEGORIES


def normalize_quest_master_record(record, now=None):
    category = normalize_schedule_category(record.get("category"))
    limited = category in LIMITED_MASTER_CATEGORIES
    timestamp = _timestamp(now)
    normalized = {
        "quest_id": str(record.get("quest_id") or make_quest_id(record)),
        "name": str(record.get("name", "")).strip(),
        "quest_name": str(record.get("quest_name", "")).strip(),
        "attribute": str(record.get("attribute", "")).strip(),
        "difficulty": str(record.get("difficulty", "")).strip(),
        "category": category,
        "group_name": str(record.get("group_name", "")).strip(),
        "availability_type": (
            normalize_availability_type(record.get("availability_type"))
            if limited
            else AVAILABILITY_SCHEDULED
        ),
        "period_end_date": (
            str(record.get("period_end_date", "")).strip()
            if limited
            else ""
        ),
        "source_type": str(record.get("source_type", "manual")).strip()
        or "manual",
        "source_url": str(record.get("source_url", "")).strip(),
        "published": bool(record.get("published", True)),
        "created_at": str(record.get("created_at", "")).strip()
        or timestamp,
        "updated_at": str(record.get("updated_at", "")).strip()
        or timestamp,
    }
    return normalized


def normalize_quest_master(records, now=None):
    normalized = []
    positions = {}
    for record in records or []:
        item = normalize_quest_master_record(record, now=now)
        key = quest_master_key(item)
        if not all(key):
            continue
        if key in positions:
            normalized[positions[key]] = item
        else:
            positions[key] = len(normalized)
            normalized.append(item)
    return normalized


def master_record_from_schedule(schedule, now=None):
    required = ("name", "attribute", "difficulty", "category")
    if not all(str(schedule.get(field, "")).strip() for field in required):
        return None
    timestamp = _timestamp(now)
    return normalize_quest_master_record(
        {
            "quest_id": schedule.get("quest_id", ""),
            "name": schedule.get("name", ""),
            "quest_name": schedule.get("quest_name", ""),
            "attribute": schedule.get("attribute", ""),
            "difficulty": schedule.get("difficulty", ""),
            "category": schedule.get("category", ""),
            "group_name": schedule.get("group_name", ""),
            "availability_type": schedule.get(
                "availability_type", AVAILABILITY_SCHEDULED
            ),
            "period_end_date": schedule.get("period_end_date", ""),
            "source_type": schedule.get("source_type", "verified"),
            "source_url": schedule.get("source_url", ""),
            "published": True,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        now=now,
    )


def upsert_quest_master(records, schedules, now=None):
    timestamp = _timestamp(now)
    merged = normalize_quest_master(records, now=now)
    positions = {
        quest_master_key(record): index
        for index, record in enumerate(merged)
    }
    added = 0
    updated = 0
    skipped = 0

    for schedule in schedules or []:
        incoming = master_record_from_schedule(schedule, now=now)
        if incoming is None:
            skipped += 1
            continue
        key = quest_master_key(incoming)
        position = positions.get(key)
        if position is None:
            positions[key] = len(merged)
            merged.append(incoming)
            added += 1
            continue

        current = merged[position]
        combined = dict(current)
        for field in (
            "name",
            "quest_name",
            "attribute",
            "difficulty",
            "category",
            "group_name",
            "availability_type",
            "period_end_date",
            "source_type",
            "source_url",
        ):
            value = incoming.get(field)
            if value not in (None, ""):
                combined[field] = value
        combined["published"] = True
        combined["quest_id"] = current["quest_id"]
        combined["created_at"] = current["created_at"]
        combined["updated_at"] = timestamp
        merged[position] = normalize_quest_master_record(combined, now=now)
        updated += 1

    return merged, added, updated, skipped


def master_expired(record, today=None):
    if not is_limited_master(record):
        return False
    end_text = str(record.get("period_end_date", "")).strip()
    if not end_text:
        return False
    try:
        end_date = datetime.strptime(end_text, "%Y-%m-%d").date()
    except ValueError:
        return False
    return (today or date.today()) > end_date


def search_quest_master(records, query="", include_expired=False, today=None):
    needle = normalize_master_name(query)
    matches = []
    for record in normalize_quest_master(records):
        if not record.get("published", True):
            continue
        if not include_expired and master_expired(record, today=today):
            continue
        haystack = normalize_master_name(" ".join(
            str(record.get(field, ""))
            for field in (
                "name",
                "quest_name",
                "attribute",
                "difficulty",
                "category",
                "group_name",
            )
        ))
        if needle and needle not in haystack:
            continue
        matches.append(record)
    return sorted(
        matches,
        key=lambda item: (
            item.get("category", ""),
            item.get("difficulty", ""),
            item.get("name", ""),
        ),
    )


def schedule_from_master(record, game_date, start_time="12:00"):
    master = normalize_quest_master_record(record)
    if isinstance(game_date, datetime):
        game_date = game_date.date()
    if isinstance(game_date, str):
        game_date = datetime.strptime(game_date, "%Y-%m-%d").date()
    if not isinstance(game_date, date):
        raise ValueError("掲載日が不正です。")
    if hasattr(start_time, "strftime"):
        start_text = start_time.strftime("%H:%M")
    else:
        start_text = str(start_time).strip()
        datetime.strptime(start_text, "%H:%M")

    return {
        "quest_id": master["quest_id"],
        "year": game_date.year,
        "date": f"{game_date.month}/{game_date.day}",
        "start_time": start_text,
        "end_time": "11:59",
        "end_next_day": True,
        "name": master["name"],
        "quest_name": master["quest_name"],
        "attribute": master["attribute"],
        "difficulty": master["difficulty"],
        "category": master["category"],
        "group_name": master["group_name"],
        "availability_type": AVAILABILITY_SCHEDULED,
        "period_end_date": "",
        "source_type": "master",
        "source_url": master["source_url"],
        "confirmed_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "published": True,
    }


def delete_quest_master(records, quest_ids):
    targets = {str(value) for value in quest_ids}
    return [
        record
        for record in normalize_quest_master(records)
        if str(record.get("quest_id")) not in targets
    ]


def parse_master_bulk_text(text, default_category):
    """名前｜属性｜難易度（｜カテゴリ）の複数行入力を解析する。"""
    records = []
    errors = []
    for line_number, raw_line in enumerate(str(text or "").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        normalized = line.replace("｜", "|").replace("\t", "|")
        if "|" not in normalized:
            normalized = normalized.replace(",", "|").replace("、", "|")
        parts = [part.strip() for part in normalized.split("|")]
        if len(parts) not in (3, 4) or not all(parts[:3]):
            errors.append(
                f"{line_number}行目：名前｜属性｜難易度の形式で入力してください。"
            )
            continue
        category = normalize_schedule_category(
            parts[3] if len(parts) == 4 else default_category
        )
        records.append({
            "name": parts[0],
            "attribute": parts[1],
            "difficulty": parts[2],
            "category": category,
        })
    return records, errors

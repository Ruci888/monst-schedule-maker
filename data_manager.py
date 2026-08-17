import json
import shutil
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def load_json(filename):
    file_path = BASE_DIR / filename

    try:
        with file_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def load_schedules():
    return load_json("schedules.json")


def load_events():
    return load_json("events.json")


def save_json(filename, data):
    """JSONを壊さずに保存し、変更前データをbackupsへ退避する。"""
    file_path = BASE_DIR / filename
    backup_dir = BASE_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)

    if file_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{file_path.stem}_{timestamp}.json"
        shutil.copy2(file_path, backup_path)

    temporary_path = file_path.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

    temporary_path.replace(file_path)


def save_schedules(schedules):
    save_json("schedules.json", schedules)


def save_events(events):
    save_json("events.json", events)

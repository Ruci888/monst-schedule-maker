import json
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

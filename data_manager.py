import json
import shutil
from datetime import datetime
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent

# IMPORTANT:
# Set this to the SAME GitHub owner value that is currently working
# in the public maker.
GITHUB_OWNER = "Ruci888"
GITHUB_REPOSITORY = "monst-schedule-maker"
GITHUB_BRANCH = "main"
GITHUB_RAW_BASE = (
    f"https://raw.githubusercontent.com/"
    f"{GITHUB_OWNER}/{GITHUB_REPOSITORY}/{GITHUB_BRANCH}"
)

REMOTE_DATA_FILES = {
    "schedules.json",
    "events.json",
    "quest_master.json",
}


class RemoteDataError(RuntimeError):
    """Raised when public data cannot be loaded from GitHub."""


def load_local_json(filename):
    """Load a local JSON list. Used by admin/local-only files."""
    file_path = BASE_DIR / filename
    try:
        with file_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def load_remote_json(filename):
    """Load public shared JSON from the GitHub repository without a token."""
    if filename not in REMOTE_DATA_FILES:
        raise RemoteDataError(
            f"取得が許可されていないファイルです: {filename}"
        )

    url = f"{GITHUB_RAW_BASE}/{filename}"
    try:
        response = requests.get(url, timeout=(5, 15))
        response.raise_for_status()
    except requests.RequestException as error:
        raise RemoteDataError(
            f"最新データを取得できませんでした: {filename}"
        ) from error

    try:
        data = response.json()
    except ValueError as error:
        raise RemoteDataError(
            f"取得したJSONを読み込めませんでした: {filename}"
        ) from error

    if not isinstance(data, list):
        raise RemoteDataError(
            f"取得したデータ形式が不正です: {filename}"
        )

    return data


def load_json(filename):
    """
    Keep the original admin-compatible API.

    Shared public data uses GitHub as the source of truth.
    Other admin files continue to use local JSON when this function
    is used directly.
    """
    if filename in REMOTE_DATA_FILES:
        return load_remote_json(filename)
    return load_local_json(filename)


def load_schedules():
    return load_remote_json("schedules.json")


def load_events():
    return load_remote_json("events.json")


def load_quest_master():
    return load_remote_json("quest_master.json")


# ------------------------------------------------------------------
# Backward-compatible local save functions required by admin_app.py.
# When GitHub is configured, admin_app.py uses github_storage.py and
# save_remote_json(). These functions remain as the existing fallback.
# ------------------------------------------------------------------

def save_json(filename, data):
    """Save local JSON safely and back up the previous local file."""
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


def save_quest_master(records):
    save_json("quest_master.json", records)

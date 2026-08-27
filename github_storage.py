import base64
import json

import requests
import streamlit as st


ALLOWED_UPDATE_FILES = {
    "schedules.json",
    "events.json",
    "quest_master.json",
    "schedule_candidates.json",
    "event_candidates.json",
    "fetch_errors.json",
    "fetch_status.json",
}
GITHUB_API = "https://api.github.com"


class GitHubStorageError(RuntimeError):
    pass


def get_settings():
    try:
        settings = st.secrets["github"]
        return {
            "token": settings["token"],
            "owner": settings["owner"],
            "repository": settings["repository"],
            "branch": settings.get("branch", "main"),
        }
    except (KeyError, FileNotFoundError):
        return None


def is_configured():
    return get_settings() is not None


def validate_filename(filename):
    if filename not in ALLOWED_UPDATE_FILES:
        raise GitHubStorageError(f"更新が許可されていないファイルです: {filename}")


def headers(settings):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings['token']}",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "MonstScheduleAdmin/1.1",
    }


def contents_url(settings, filename):
    return (
        f"{GITHUB_API}/repos/{settings['owner']}/"
        f"{settings['repository']}/contents/{filename}"
    )


def request_file(filename):
    validate_filename(filename)
    settings = get_settings()
    if not settings:
        raise GitHubStorageError("GitHub連携が未設定です。")

    response = requests.get(
        contents_url(settings, filename),
        headers=headers(settings),
        params={"ref": settings["branch"]},
        timeout=(5, 15),
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise GitHubStorageError(
            f"GitHubからデータを取得できませんでした（{response.status_code}）。"
        )
    return response.json()


def load_remote_json(filename):
    file_data = request_file(filename)
    if file_data is None:
        return []
    try:
        decoded = base64.b64decode(file_data["content"]).decode("utf-8")
        data = json.loads(decoded)
    except (KeyError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GitHubStorageError("GitHub上のJSONを読み込めませんでした。") from error
    return data if isinstance(data, list) else []


def save_remote_json(filename, data, commit_message):
    validate_filename(filename)
    settings = get_settings()
    if not settings:
        raise GitHubStorageError("GitHub連携が未設定です。")

    current_file = request_file(filename)
    encoded = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=4).encode("utf-8")
    ).decode("ascii")
    payload = {
        "message": commit_message,
        "content": encoded,
        "branch": settings["branch"],
    }
    if current_file:
        payload["sha"] = current_file["sha"]

    response = requests.put(
        contents_url(settings, filename),
        headers=headers(settings),
        json=payload,
        timeout=(5, 20),
    )
    if response.status_code not in (200, 201):
        raise GitHubStorageError(
            f"GitHubへ保存できませんでした（{response.status_code}）。"
        )
    return response.json()

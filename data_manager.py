import json
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent

# 公開メーカーが参照するGitHub上の共通JSON。
# owner/repository は実際の公開リポジトリに合わせて設定してください。
GITHUB_OWNER = "YOUR_GITHUB_OWNER"
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
    """公開データをGitHubから取得できない場合のエラー。"""


def load_local_json(filename):
    """開発・保守用のローカルJSON読込。公開データの正本には使用しない。"""
    file_path = BASE_DIR / filename
    try:
        with file_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def load_remote_json(filename):
    """GitHub Public Repository上のJSONを読み取る。Tokenは使用しない。"""
    if filename not in REMOTE_DATA_FILES:
        raise RemoteDataError(f"取得が許可されていないファイルです: {filename}")

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
    except (ValueError, json.JSONDecodeError) as error:
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
    公開データはGitHubを正本として取得する。
    その他のローカル管理ファイルは従来どおりローカルから読む。
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

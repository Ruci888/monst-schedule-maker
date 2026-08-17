import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from data_manager import save_json


OFFICIAL_NEWS_URL = "https://www.monster-strike.com/news/"
ALLOWED_DOMAINS = {"www.monster-strike.com"}
MAX_RESPONSE_BYTES = 4_000_000
ARTICLE_LIMIT = 30

DATE_RANGE_PATTERN = re.compile(
    r"(?P<start_year>20\d{2})年"
    r"(?P<start_month>\d{1,2})月"
    r"(?P<start_day>\d{1,2})日"
    r"(?:（[^）]+）|\([^\)]+\))?\s*"
    r"(?P<start_hour>\d{1,2}):(?P<start_minute>\d{2})\s*"
    r"[～〜]\s*"
    r"(?:(?P<end_year>20\d{2})年)?"
    r"(?P<end_month>\d{1,2})月"
    r"(?P<end_day>\d{1,2})日"
    r"(?:（[^）]+）|\([^\)]+\))?\s*"
    r"(?P<end_hour>\d{1,2}):(?P<end_minute>\d{2})"
)

PERIOD_LABELS = (
    "初出現日時",
    "初出現日程",
    "初出現期間",
    "出現期間",
    "開催期間",
    "対象期間",
)


def validate_url(url):
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_DOMAINS


def fetch_html(url):
    if not validate_url(url):
        raise ValueError(f"許可されていないURLです: {url}")

    response = requests.get(
        url,
        timeout=(5, 15),
        headers={"User-Agent": "MonstScheduleMaker/1.1"},
        allow_redirects=True,
    )
    response.raise_for_status()

    if not validate_url(response.url):
        raise ValueError(f"許可されていないURLへ転送されました: {response.url}")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError("取得サイズが上限を超えました。")

    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def normalize_space(value):
    return re.sub(r"\s+", " ", value).strip()


def extract_article_links(index_html):
    soup = BeautifulSoup(index_html, "html.parser")
    links = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        url = urljoin(OFFICIAL_NEWS_URL, anchor["href"])
        path = urlparse(url).path
        if not re.fullmatch(r"/news/20\d{6}(?:_\d+)?\.html", path):
            continue
        if url in seen or not validate_url(url):
            continue
        seen.add(url)
        links.append(url)
        if len(links) >= ARTICLE_LIMIT:
            break

    return links


def parse_datetime_range(text):
    for label in PERIOD_LABELS:
        label_position = text.find(label)
        if label_position == -1:
            continue
        nearby_text = text[label_position:label_position + 220]
        match = DATE_RANGE_PATTERN.search(nearby_text)
        if match:
            return range_from_match(match), label

    match = DATE_RANGE_PATTERN.search(text)
    if match:
        return range_from_match(match), "ラベル未判定"
    return None, None


def range_from_match(match):
    values = match.groupdict()
    start_year = int(values["start_year"])
    end_year = int(values["end_year"] or start_year)
    start = datetime(
        start_year,
        int(values["start_month"]),
        int(values["start_day"]),
        int(values["start_hour"]),
        int(values["start_minute"]),
    )
    end = datetime(
        end_year,
        int(values["end_month"]),
        int(values["end_day"]),
        int(values["end_hour"]),
        int(values["end_minute"]),
    )
    if end < start:
        end = end.replace(year=end.year + 1)
    return start, end


def classify_event(title):
    excluded_words = ("SNS", "グッズ", "リアルイベント", "チケット")
    if any(word in title for word in excluded_words):
        return None
    if "獣神化" in title or "真獣神化" in title:
        return "獣神化情報"
    if "ガチャ" in title or "獣神祭" in title:
        return "ガチャ"
    if "コラボ" in title or "期間限定イベント" in title:
        return "コラボ・期間限定"
    if any(word in title for word in ("天魔", "星墓", "覇者の塔", "未開", "神獣")):
        return "定期コンテンツ"
    if any(word in title for word in ("キャンペーン", "追憶の書庫", "英雄の神殿")):
        return "育成キャンペーン"
    return None


def clean_event_name(title):
    title = re.sub(r"\s*[-｜|].*?モンスト公式.*$", "", title)
    return normalize_space(title)


def extract_high_difficulty(title, text, source_url, fetched_at):
    difficulty_match = re.search(r"新(黎絶|轟絶|爆絶|超絶)クエスト", title)
    name_match = re.search(r"新(?:黎絶|轟絶|爆絶|超絶)クエスト（([^）]+)）", title)
    if not difficulty_match or not name_match:
        return None

    date_range, period_label = parse_datetime_range(text)
    if not date_range or period_label not in ("初出現日時", "初出現日程"):
        return None

    start, end = date_range
    attribute_match = re.search(r"([火水木光闇])属性\s*★\d", text)
    quest_match = re.search(
        rf"{difficulty_match.group(1)}クエスト「([^」]+)」",
        text,
    )
    return {
        "year": start.year,
        "date": f"{start.month}/{start.day}",
        "start_time": start.strftime("%H:%M"),
        "end_time": end.strftime("%H:%M"),
        "name": name_match.group(1).strip(),
        "quest_name": quest_match.group(1).strip() if quest_match else "",
        "attribute": attribute_match.group(1) if attribute_match else "",
        "difficulty": difficulty_match.group(1),
        "category": "high_difficulty",
        "source_type": "official",
        "source_url": source_url,
        "fetched_at": fetched_at,
        "review_status": "needs_review",
        "published": False,
    }


def extract_event(title, text, source_url, fetched_at):
    category = classify_event(title)
    if not category:
        return None
    date_range, period_label = parse_datetime_range(text)
    if not date_range:
        return None

    start, end = date_range
    name = clean_event_name(title)
    review_reason = ""
    if period_label == "ラベル未判定":
        review_reason = "期間ラベルを特定できませんでした。"

    return {
        "name": name,
        "short_name": name[:18],
        "category": category,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "source_type": "official",
        "source_url": source_url,
        "fetched_at": fetched_at,
        "period_label": period_label,
        "review_status": "needs_review",
        "review_reason": review_reason,
        "published": False,
    }


def deduplicate(items, fields):
    results = []
    seen = set()
    for item in items:
        key = tuple(item.get(field, "") for field in fields)
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
    return results


def run_update():
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    schedule_candidates = []
    event_candidates = []
    errors = []

    try:
        index_html = fetch_html(OFFICIAL_NEWS_URL)
        article_links = extract_article_links(index_html)
    except Exception as error:
        article_links = []
        errors.append({
            "source_url": OFFICIAL_NEWS_URL,
            "reason": str(error),
            "fetched_at": fetched_at,
        })

    for article_url in article_links:
        try:
            html = fetch_html(article_url)
            soup = BeautifulSoup(html, "html.parser")
            title_node = soup.find("h1") or soup.find("title")
            title = normalize_space(title_node.get_text(" ")) if title_node else ""
            text = normalize_space(soup.get_text(" "))
            if not title or not text:
                raise ValueError("記事タイトルまたは本文を取得できませんでした。")

            schedule = extract_high_difficulty(title, text, article_url, fetched_at)
            if schedule:
                schedule_candidates.append(schedule)

            event = extract_event(title, text, article_url, fetched_at)
            if event:
                event_candidates.append(event)
        except Exception as error:
            errors.append({
                "source_url": article_url,
                "reason": str(error),
                "fetched_at": fetched_at,
            })

    schedule_candidates = deduplicate(
        schedule_candidates,
        ("year", "date", "start_time", "name"),
    )
    event_candidates = deduplicate(
        event_candidates,
        ("name", "start_date", "end_date"),
    )

    save_json("schedule_candidates.json", schedule_candidates)
    save_json("event_candidates.json", event_candidates)
    save_json("fetch_errors.json", errors)
    save_json("fetch_status.json", [{
        "fetched_at": fetched_at,
        "article_count": len(article_links),
        "schedule_candidate_count": len(schedule_candidates),
        "event_candidate_count": len(event_candidates),
        "error_count": len(errors),
    }])

    return {
        "fetched_at": fetched_at,
        "article_count": len(article_links),
        "schedule_candidate_count": len(schedule_candidates),
        "event_candidate_count": len(event_candidates),
        "error_count": len(errors),
    }


if __name__ == "__main__":
    print(run_update())

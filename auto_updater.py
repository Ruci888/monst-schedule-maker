import re
from datetime import date, datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from data_manager import save_json


OFFICIAL_NEWS_URL = "https://www.monster-strike.com/news/"
OFFICIAL_HOME_URL = "https://www.monster-strike.com/"
OFFICIAL_INDEX_URLS = (OFFICIAL_NEWS_URL, OFFICIAL_HOME_URL)
ALLOWED_DOMAINS = {"www.monster-strike.com"}
MAX_RESPONSE_BYTES = 4_000_000
ARTICLE_LIMIT = 30
UPDATER_VERSION = "1.1.7"
ARTICLE_PATH_PATTERN = re.compile(r"/news/20\d{6}(?:_\d+)?\.html/?$")
ARTICLE_URL_PATTERN = re.compile(
    r"(?:https://www\.monster-strike\.com)?/news/20\d{6}(?:_\d+)?\.html"
)

DATE_RANGE_PATTERN = re.compile(
    r"(?P<start_year>20\d{2})年\s*"
    r"(?P<start_month>\d{1,2})月\s*"
    r"(?P<start_day>\d{1,2})日"
    r"(?:（[^）]+）|\([^\)]+\))?\s*"
    r"(?P<start_hour>\d{1,2}):(?P<start_minute>\d{2})\s*"
    r"[～〜]\s*"
    r"(?:(?P<end_year>20\d{2})年\s*)?"
    r"(?P<end_month>\d{1,2})月\s*"
    r"(?P<end_day>\d{1,2})日"
    r"(?:（[^）]+）|\([^\)]+\))?\s*"
    r"(?P<end_hour>\d{1,2}):(?P<end_minute>\d{2})"
)
SINGLE_DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})年\s*"
    r"(?P<month>\d{1,2})月\s*"
    r"(?P<day>\d{1,2})日"
    r"(?:（[^）]+）|\([^\)]+\))?"
    r"(?:\s*(?P<hour>\d{1,2}):(?P<minute>\d{2}))?"
)

DEFAULT_PERIOD_LABELS = (
    "初出現日時",
    "初出現日程",
    "初出現期間",
    "出現期間",
    "ガチャ開催期間",
    "開催期間",
    "対象期間",
    "実施期間",
)
EXCLUDED_SECTION_WORDS = (
    "SNS",
    "Xキャンペーン",
    "公式X",
    "グッズ",
    "チケット",
    "WEBショップ",
    "Webショップ",
    "パックを販売",
    "購入",
)


def validate_url(url):
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_DOMAINS


def fetch_html(url):
    # requestsは実行時だけ読み込む。テスト時に通信ライブラリを不要にするため。
    import requests

    if not validate_url(url):
        raise ValueError(f"許可されていないURLです: {url}")

    response = requests.get(
        url,
        timeout=(5, 15),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
            ),
            "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.7",
        },
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
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(index_html, "html.parser")
    links = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        url = urljoin(OFFICIAL_NEWS_URL, anchor["href"])
        if not ARTICLE_PATH_PATTERN.fullmatch(urlparse(url).path):
            continue
        if url in seen or not validate_url(url):
            continue
        seen.add(url)
        links.append(url)
        if len(links) >= ARTICLE_LIMIT:
            break

    # aタグが変更された場合に備え、HTML内の公式記事URLも確認する。
    normalized_html = index_html.replace("\\/", "/")
    for match in ARTICLE_URL_PATTERN.finditer(normalized_html):
        url = urljoin(OFFICIAL_NEWS_URL, match.group(0))
        if url in seen or not validate_url(url):
            continue
        seen.add(url)
        links.append(url)
        if len(links) >= ARTICLE_LIMIT:
            break

    return links


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


def parse_all_datetime_ranges(text):
    return [range_from_match(match) for match in DATE_RANGE_PATTERN.finditer(text)]


def first_range_after_label(text, label, search_length=500):
    position = text.find(label)
    while position != -1:
        match = DATE_RANGE_PATTERN.search(text[position:position + search_length])
        if match:
            return range_from_match(match)
        position = text.find(label, position + len(label))
    return None


def select_datetime_range(text, preferred_labels=()):
    labels = tuple(preferred_labels) + DEFAULT_PERIOD_LABELS
    checked = set()
    for label in labels:
        if label in checked:
            continue
        checked.add(label)
        date_range = first_range_after_label(text, label)
        if date_range:
            return date_range, label

    match = DATE_RANGE_PATTERN.search(text)
    if match:
        return range_from_match(match), "ラベル未判定"
    return None, None


def first_single_date_after_label(text, labels):
    for label in labels:
        position = text.find(label)
        if position == -1:
            continue
        match = SINGLE_DATE_PATTERN.search(text[position:position + 250])
        if not match:
            continue
        values = match.groupdict()
        return datetime(
            int(values["year"]),
            int(values["month"]),
            int(values["day"]),
            int(values["hour"] or 0),
            int(values["minute"] or 0),
        ), label
    return None, None


def extract_sections(soup):
    sections = []
    for heading in soup.find_all(["h2", "h3"]):
        heading_text = normalize_space(heading.get_text(" "))
        if not heading_text:
            continue

        body_parts = []
        for sibling in heading.next_siblings:
            sibling_name = getattr(sibling, "name", None)
            if sibling_name in ("h2", "h3"):
                break
            if hasattr(sibling, "get_text"):
                value = normalize_space(sibling.get_text(" "))
            else:
                value = normalize_space(str(sibling))
            if value:
                body_parts.append(value)
        section_text = normalize_space(" ".join([heading_text, *body_parts]))
        sections.append((heading_text, section_text))
    return sections


def build_event_candidate(
    name,
    short_name,
    category,
    start,
    end,
    source_url,
    fetched_at,
    period_label,
    review_reason,
):
    return {
        "name": normalize_space(name),
        "short_name": normalize_space(short_name)[:18],
        "category": category,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "description": "",
        "source_type": "official",
        "source_url": source_url,
        "fetched_at": fetched_at,
        "period_label": period_label,
        "review_status": "needs_review",
        "review_reason": review_reason,
        "published": False,
    }


def section_definition(heading, text):
    combined = f"{heading} {text}"
    if any(word in combined for word in EXCLUDED_SECTION_WORDS):
        return None

    if "ガチャ" in heading and any(word in heading for word in ("開催", "登場")):
        gacha_name = quoted_name(heading)
        if not gacha_name:
            gacha_name = re.sub(r"^.*?ガチャ", "", heading)
            gacha_name = re.sub(r"(?:開催|登場).*$", "", gacha_name)
            gacha_name = normalize_space(gacha_name).strip("!！『』「」 ")
        if not gacha_name:
            gacha_name = "期間限定"
        return f"{gacha_name}ガチャ", f"{gacha_name}ガチャ", "ガチャ"

    if "英雄の神殿" in heading or (
        "わくわくの実" in heading and "2個" in heading
    ):
        return (
            "英雄の神殿 わくわくの実2個",
            "神殿CP・わくわく×2",
            "育成キャンペーン",
        )
    if "追憶の書庫" in heading and any(
        word in heading for word in ("金卵", "金の卵", "排出率", "2倍")
    ):
        return (
            "追憶の書庫 金卵排出率2倍",
            "書庫卵2倍CP",
            "育成キャンペーン",
        )
    if "追憶の書庫" in heading:
        return "追憶の書庫キャンペーン", "書庫CP", "育成キャンペーン"
    if "クエストサーチ" in heading:
        return "クエストサーチミッション", "サーチミッション", "ミッション"
    if "タイムシフト" in heading:
        return "タイムシフトミッション", "タイムシフトミッション", "ミッション"
    if "スタミナ" in heading and any(
        word in heading for word in ("バック", "返却", "消費", "回復")
    ):
        return (
            "マルチ・スタミナバックキャンペーン",
            "マルチ・スタミナバックCP",
            "マルチキャンペーン",
        )
    if "期間限定ミッション" in heading:
        if any(
            word in text
            for word in ("特設サイト", "キャンペーンページ", "本キャンペーンに参加")
        ):
            return None
        if any(word in text for word in ("入手方法", "その他", "交代劇")):
            return (
                "その他クリアミッション",
                "その他クリアミッション",
                "ミッション",
            )
    if "セレクションミッション" in heading:
        return "コラボミッション", "コラボミッション", "ミッション"
    if "ミッション" in heading:
        name = re.sub(r"^[!！◆◇●・\s]+", "", heading)
        return name[:32], name[:10], "ミッション"
    return None


def library_campaign_short_name(section_text):
    target_position = section_text.find("対象クエスト")
    target_text = (
        section_text[target_position:]
        if target_position != -1
        else section_text
    )
    attributes = re.findall(r"([火水木光闇])属性クエスト", target_text)

    ordered_attributes = []
    for attribute in attributes:
        if attribute not in ordered_attributes:
            ordered_attributes.append(attribute)

    if not ordered_attributes:
        return "書庫卵2倍CP"
    attribute_order = "・".join(ordered_attributes)
    return f"書庫卵2倍CP({attribute_order})"


def extract_section_events(sections, source_url, fetched_at):
    candidates = []
    for heading, section_text in sections:
        definition = section_definition(heading, section_text)
        if not definition:
            continue

        name, short_name, category = definition
        if name == "追憶の書庫 金卵排出率2倍":
            short_name = library_campaign_short_name(section_text)
        ranges = parse_all_datetime_ranges(section_text)
        for interval_number, (start, end) in enumerate(ranges, start=1):
            interval_name = name
            if len(ranges) > 1:
                interval_name = f"{name}（第{interval_number}期間）"
            candidates.append(build_event_candidate(
                name=interval_name,
                short_name=short_name,
                category=category,
                start=start,
                end=end,
                source_url=source_url,
                fetched_at=fetched_at,
                period_label="記事内項目",
                review_reason="記事内のキャンペーン項目から個別抽出しました。",
            ))
    return candidates


def clean_event_name(title):
    title = re.sub(r"\s*[-｜|].*?モンスト公式.*$", "", title)
    title = re.sub(r"\s*\|\s*モンスターストライク.*$", "", title)
    return normalize_space(title)


def quoted_name(title):
    matches = re.findall(r"[「『]([^」』]+)[」』]", title)
    return matches[0].strip() if matches else ""


def extract_primary_event(title, text, source_url, fetched_at):
    clean_title = clean_event_name(title)

    if "獣神化" in clean_title or "真獣神化" in clean_title:
        start, period_label = first_single_date_after_label(
            text,
            ("解禁日時", "獣神化・改 解禁日時", "獣神化 解禁日時"),
        )
        if not start:
            return None
        name = quoted_name(clean_title) or clean_title
        return build_event_candidate(
            name=name,
            short_name=(
                f"{name}、獣神化・改"
                if "獣神化・改" in clean_title
                else f"{name}、獣神化"
            ),
            category="獣神化情報",
            start=start,
            end=start,
            source_url=source_url,
            fetched_at=fetched_at,
            period_label=period_label,
            review_reason="解禁日時から抽出しました。キャラ名を確認してください。",
        )

    if "未開の幻洞" in clean_title:
        date_range, period_label = select_datetime_range(
            text, ("初出現期間", "出現期間")
        )
        if not date_range:
            return None
        start, end = date_range
        return build_event_candidate(
            "未開の幻洞",
            "未開の幻洞",
            "定期コンテンツ",
            start,
            end,
            source_url,
            fetched_at,
            period_label,
            "毎月14日開始の定期コンテンツとして分類しました。",
        )

    if "覇者の塔" in clean_title:
        date_range, period_label = select_datetime_range(text, ("出現期間",))
        if not date_range:
            return None
        start, end = date_range
        return build_event_candidate(
            "覇者の塔",
            "覇者の塔",
            "定期コンテンツ",
            start,
            end,
            source_url,
            fetched_at,
            period_label,
            "定期コンテンツとして分類しました。",
        )

    if any(word in clean_title for word in ("天魔", "破界の星墓", "神獣")):
        date_range, period_label = select_datetime_range(text)
        if not date_range:
            return None
        start, end = date_range
        name = quoted_name(clean_title) or clean_title[:32]
        return build_event_candidate(
            name,
            name[:18],
            "定期コンテンツ",
            start,
            end,
            source_url,
            fetched_at,
            period_label,
            "定期コンテンツとして分類しました。",
        )

    # 記念キャンペーン記事は上の項目単位抽出だけを使う。
    if "コラボ" in clean_title and "キャンペーン" not in clean_title:
        date_range, period_label = select_datetime_range(
            text,
            ("コラボイベント開催期間", "コラボ開催期間", "開催期間"),
        )
        if not date_range:
            return None
        start, end = date_range
        collab_name = quoted_name(clean_title)
        if not collab_name:
            match = re.search(r"【([^】]+×モンスト)】", clean_title)
            collab_name = match.group(1) if match else "コラボイベント"
        collab_name = collab_name.replace("×モンスト", "")
        return build_event_candidate(
            f"{collab_name}コラボ",
            f"{collab_name}コラボ",
            "コラボ・期間限定",
            start,
            end,
            source_url,
            fetched_at,
            period_label,
            "コラボ全体の開催期間として抽出しました。",
        )

    if "ガチャ" in clean_title or "獣神祭" in clean_title:
        date_range, period_label = select_datetime_range(
            text,
            ("ガチャ開催期間", "開催期間"),
        )
        if not date_range:
            return None
        start, end = date_range
        name = quoted_name(clean_title)
        if "モンスト夏休み" in clean_title:
            name = "モンスト夏休み2026 復刻ガチャ"
        elif not name and "アゲインガチャ" in clean_title:
            name = "アゲインガチャ"
        elif not name:
            name = clean_title[:32]
        return build_event_candidate(
            name,
            name[:18],
            "ガチャ",
            start,
            end,
            source_url,
            fetched_at,
            period_label,
            "ガチャ開催期間を優先して抽出しました。",
        )

    return None


def extract_high_difficulty(title, text, source_url, fetched_at):
    difficulty_match = re.search(r"新(黎絶|轟絶|爆絶|超絶)クエスト", title)
    name_match = re.search(r"新(?:黎絶|轟絶|爆絶|超絶)クエスト（([^）]+)）", title)
    if not difficulty_match or not name_match:
        return None

    date_range, period_label = select_datetime_range(
        text, ("初出現日時", "初出現日程")
    )
    if not date_range or period_label not in ("初出現日時", "初出現日程"):
        return None

    start, end = date_range
    attribute_match = re.search(r"([火水木光闇])属性\s*★\d", text)
    quest_match = re.search(rf"{difficulty_match.group(1)}クエスト「([^」]+)」", text)
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
        "review_reason": "初出現日時から抽出しました。",
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


def normalize_known_event_name(event):
    normalized = dict(event)
    name = normalize_space(normalized.get("name", ""))

    # 同じガチャが記事タイトルと記事内見出しから異なる名称で取得されても、
    # 保存前に公式の短い名称へそろえて重複判定できるようにする。
    if "アゲインガチャ" in name:
        normalized["name"] = "アゲインガチャ"
        normalized["short_name"] = "アゲインガチャ"
        normalized["category"] = "周年CP"
        normalized["review_reason"] = (
            "周年イベントとして開催されるガチャのため周年CPに分類しました。"
        )

    return normalized


def japan_today():
    return datetime.now(ZoneInfo("Asia/Tokyo")).date()


def remove_expired_events(events, reference_date=None):
    current_date = reference_date or japan_today()
    active = []
    expired_count = 0
    for event in events:
        if date.fromisoformat(event["end_date"]) < current_date:
            expired_count += 1
        else:
            active.append(event)
    return active, expired_count


def extract_event_candidates(
    title,
    text,
    sections,
    source_url,
    fetched_at,
    reference_date=None,
):
    candidates = [
        normalize_known_event_name(candidate)
        for candidate in extract_section_events(sections, source_url, fetched_at)
    ]
    primary = extract_primary_event(title, text, source_url, fetched_at)
    if primary:
        primary = normalize_known_event_name(primary)
        if primary["category"] == "コラボ・期間限定":
            for candidate in candidates:
                if candidate["category"] == "ガチャ":
                    candidate["category"] = "コラボガチャ"
                    if not candidate["name"].endswith("コラボガチャ"):
                        candidate["name"] = re.sub(
                            r"ガチャ$", "コラボガチャ", candidate["name"]
                        )
                    if not candidate["short_name"].endswith("コラボガチャ"):
                        candidate["short_name"] = re.sub(
                            r"ガチャ$", "コラボガチャ", candidate["short_name"]
                        )
                    candidate["review_reason"] = (
                        "コラボ記事内のガチャとして分類しました。"
                    )
                elif candidate["category"] == "ミッション":
                    candidate["category"] = "コラボミッション"
                    candidate["review_reason"] = (
                        "コラボ本体記事内のミッションとして分類しました。"
                    )
        # 同じ記事の見出しと記事全体から同一イベントを二重取得した場合は、
        # 短く整形済みのprimary候補を優先する。
        candidates = [
            candidate
            for candidate in candidates
            if not (
                candidate["start_date"] == primary["start_date"]
                and candidate["end_date"] == primary["end_date"]
                and (
                    candidate["category"] == primary["category"]
                    or (
                        primary["category"] == "周年CP"
                        and candidate["category"] == "ガチャ"
                    )
                )
            )
        ]
        candidates.append(primary)
    candidates = deduplicate(candidates, ("name", "start_date", "end_date"))
    return remove_expired_events(candidates, reference_date)


def run_update():
    from bs4 import BeautifulSoup

    fetched_at = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")
    schedule_candidates = []
    event_candidates = []
    errors = []
    expired_event_count = 0
    article_links = []
    seen_links = set()

    for index_url in OFFICIAL_INDEX_URLS:
        try:
            index_html = fetch_html(index_url)
            for article_url in extract_article_links(index_html):
                if article_url in seen_links:
                    continue
                seen_links.add(article_url)
                article_links.append(article_url)
                if len(article_links) >= ARTICLE_LIMIT:
                    break
        except Exception as error:
            errors.append({
                "source_url": index_url,
                "reason": str(error),
                "fetched_at": fetched_at,
            })
        if len(article_links) >= ARTICLE_LIMIT:
            break

    if not article_links:
        errors.append({
            "source_url": OFFICIAL_NEWS_URL,
            "reason": (
                "公式ページから記事リンクを1件も抽出できませんでした。"
                "HTML構造またはアクセス制限を確認してください。"
            ),
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

            article_events, article_expired_count = extract_event_candidates(
                title=title,
                text=text,
                sections=extract_sections(soup),
                source_url=article_url,
                fetched_at=fetched_at,
            )
            event_candidates.extend(article_events)
            expired_event_count += article_expired_count
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
    event_candidates = [
        normalize_known_event_name(event)
        for event in event_candidates
    ]
    event_candidates = deduplicate(
        event_candidates,
        ("name", "start_date", "end_date"),
    )

    status = {
        "updater_version": UPDATER_VERSION,
        "fetched_at": fetched_at,
        "article_count": len(article_links),
        "schedule_candidate_count": len(schedule_candidates),
        "event_candidate_count": len(event_candidates),
        "expired_event_count": expired_event_count,
        "error_count": len(errors),
    }
    save_json("schedule_candidates.json", schedule_candidates)
    save_json("event_candidates.json", event_candidates)
    save_json("fetch_errors.json", errors)
    save_json("fetch_status.json", [status])
    return status


if __name__ == "__main__":
    print(run_update())

#!/usr/bin/env python3
"""Collect recent Evenki-related headlines from Google News RSS and post to Telegram.

The feed is a discovery aid, not an editorial fact checker. Posts retain the
publisher link and should be reviewed by the channel editors after publication.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
QUERIES_FILE = ROOT / "news-search-queries.json"
SOURCES_FILE = ROOT / "news-search-sources.json"
STATE_FILE = ROOT / "data" / "telegram-news-state.json"
TZ = ZoneInfo("Asia/Tbilisi")
RSS_URL = "https://news.google.com/rss/search"
BOT_API = "https://api.telegram.org"
LOOKBACK_HOURS = 36
MAX_SEEN_DAYS = 30
MAX_DIGEST_ITEMS = 40

CORE_RE = re.compile(r"эвенк|эвенки|эвенкий|эвенкия|эвенкил|эвэды|ороч[её]н|хамниган|манегр|бирар|солон|бакалдын|мучун", re.I)


def now_local() -> dt.datetime:
    return dt.datetime.now(TZ)


def load_queries() -> list[str]:
    # Use all configured ethnonym and topic queries. Region-only terms are
    # excluded because they would drown out relevant stories with local news.
    data = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    if not isinstance(data.get("queryGroups"), list):
        raise ValueError("queryGroups missing from news-search-queries.json")
    excluded = {str(value).casefold() for value in data.get("excludeExactPhrases", [])}
    terms: list[str] = []
    for group in data["queryGroups"]:
        if group.get("id") == "regions":
            continue
        for value in group.get("queries", []):
            term = str(value).strip()
            if term and term.casefold() not in excluded and term not in terms:
                terms.append(term)
    if not terms:
        raise ValueError("No usable queries found in news-search-queries.json")
    return terms


def load_source_domains() -> list[str]:
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    domains = [str(value).strip().lower() for value in data.get("domains", [])]
    domains = [value for value in domains if re.fullmatch(r"[a-z0-9.-]+|[^\s/]+", value)]
    if not domains:
        raise ValueError("No source domains found in news-search-sources.json")
    return domains


def request(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "TaezhnayaNit-NewsMonitor/1.0 (RSS reader)"} | (headers or {}),
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read()


def parse_date(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.strptime(value.strip(), "%a, %d %b %Y %H:%M:%S %Z")
        return parsed.replace(tzinfo=dt.timezone.utc).astimezone(TZ)
    except ValueError:
        try:
            parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed.replace(tzinfo=dt.timezone.utc).astimezone(TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)
        except ValueError:
            return None


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def original_source_url(url: str) -> str:
    """Follow Google News' redirect so Telegram posts point at the publisher."""
    if "news.google.com/" not in url:
        return url
    for method, extra_headers in (("HEAD", {}), ("GET", {"Range": "bytes=0-0"})):
        try:
            req = urllib.request.Request(
                url,
                method=method,
                headers={"User-Agent": "Mozilla/5.0 (compatible; TaezhnayaNit-NewsMonitor/1.0)"} | extra_headers,
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                final_url = response.geturl()
            if final_url.startswith("https://") and "news.google.com/" not in final_url:
                return final_url
        except (urllib.error.URLError, TimeoutError, ValueError):
            continue
    return url


def fetch_items() -> list[dict[str, str]]:
    terms = load_queries()
    query = " OR ".join(f'"{term.strip(chr(34))}"' for term in terms)
    domains = load_source_domains()
    domain_groups = [domains[i:i + 12] for i in range(0, len(domains), 12)]
    feeds = [f"({query}) when:2d"]
    for group in domain_groups:
        sites = " OR ".join(f"site:{domain}" for domain in group)
        feeds.append(f"({query}) ({sites}) when:2d")
    items: list[dict[str, str]] = []
    cutoff = now_local() - dt.timedelta(hours=LOOKBACK_HOURS)
    failures = 0
    for feed_query in feeds:
        params = urllib.parse.urlencode({"q": feed_query, "hl": "ru", "gl": "RU", "ceid": "RU:ru"})
        try:
            payload = request(f"{RSS_URL}?{params}")
            root = ET.fromstring(payload)
        except (urllib.error.URLError, TimeoutError, ET.ParseError) as error:
            failures += 1
            print(f"Warning: one RSS search failed: {error}", file=sys.stderr)
            continue
        for node in root.findall("./channel/item"):
            title = clean(node.findtext("title", ""))
            description = clean(node.findtext("description", ""))
            if not CORE_RE.search(f"{title} {description}"):
                continue
            published = parse_date(node.findtext("pubDate", ""))
            if not published or published < cutoff:
                continue
            link = clean(node.findtext("link", ""))
            if not link.startswith("https://"):
                continue
            source_node = node.find("source")
            source = clean(source_node.text if source_node is not None else "")
            guid = clean(node.findtext("guid", ""))
            item_id = guid or link
            items.append({
                "id": item_id,
                "title": title,
                "source": source or "Источник в Google Новостях",
                "url": original_source_url(link),
                "published": published.isoformat(timespec="minutes"),
                "day": published.date().isoformat(),
            })
    if failures == len(feeds):
        raise RuntimeError("All Google News RSS searches failed")
    # Deduplicate repeated variants within a single RSS response.
    return list({item["id"]: item for item in items}.values())


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {"version": 1, "seen": {}, "daily": {}}
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("Unsupported Telegram news state format")
    state.setdefault("seen", {})
    state.setdefault("daily", {})
    return state


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def telegram_send(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "@taiga_thread").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured in GitHub Actions secrets")
    url = f"{BOT_API}/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, ensure_ascii=False).encode("utf-8")
    result = json.loads(request(url, data=body, headers={"Content-Type": "application/json"}))
    if not result.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {result.get('description', 'unknown error')}")


def format_item(item: dict[str, str], number: int | None = None) -> str:
    prefix = f"{number}. " if number is not None else "📰 "
    return f"{prefix}{item['title']}\n{item['source']} · {item['published'][:10]}\n{item['url']}"


def send_digest(today: str, state: dict) -> None:
    items = state["daily"].get(today, [])
    if not items:
        print(f"No matching stories for {today}; digest skipped.")
        return
    selected = items[:MAX_DIGEST_ITEMS]
    parts = [f"📰 Что произошло сегодня — {today}"]
    for index, item in enumerate(selected, start=1):
        parts.append(f"{index}. {item['title']}\n{item['source']} · {item['url']}")
    if len(items) > len(selected):
        parts.append(f"Ещё {len(items) - len(selected)} публикаций доступны в ленте сайта.")
    # Telegram sendMessage allows 4096 characters. Split only between stories.
    chunks: list[str] = []
    chunk = ""
    for part in parts:
        candidate = f"{chunk}\n\n{part}" if chunk else part
        if len(candidate) > 3900 and chunk:
            chunks.append(chunk)
            chunk = part
        else:
            chunk = candidate
    if chunk:
        chunks.append(chunk)
    for piece in chunks:
        telegram_send(piece)
    print(f"Sent digest with {len(selected)} stories for {today}.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("collect", "digest"), default="collect")
    args = parser.parse_args()

    today = now_local().date().isoformat()
    state = read_state()
    found = fetch_items()
    unseen_today = [item for item in found if item["day"] == today and item["id"] not in state["seen"]]

    # Expire IDs older than a month and old digest buckets.
    expiry = now_local() - dt.timedelta(days=MAX_SEEN_DAYS)
    state["seen"] = {
        key: value for key, value in state["seen"].items()
        if (parse_date(value) or now_local()) >= expiry
    }
    state["daily"] = {day: items for day, items in state["daily"].items() if day >= (now_local().date() - dt.timedelta(days=7)).isoformat()}

    if args.mode == "collect":
        for item in unseen_today:
            telegram_send(format_item(item))
            state["seen"][item["id"]] = now_local().isoformat(timespec="minutes")
            state["daily"].setdefault(item["day"], []).append(item)
            save_state(state)
        # Remember older search results too, so they do not reappear on every run.
        for item in found:
            if item["day"] != today:
                state["seen"].setdefault(item["id"], now_local().isoformat(timespec="minutes"))
        print(f"Fetched {len(found)} candidates; posted {len(unseen_today)} new items dated today.")
    else:
        for item in unseen_today:
            state["seen"][item["id"]] = now_local().isoformat(timespec="minutes")
            state["daily"].setdefault(item["day"], []).append(item)
        send_digest(today, state)

    save_state(state)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, ET.ParseError, OSError, ValueError, RuntimeError) as error:
        print(f"News collector failed: {error}", file=sys.stderr)
        raise SystemExit(1)

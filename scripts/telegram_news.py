#!/usr/bin/env python3
"""Collect recent Evenki-related headlines from Google News RSS and post to Telegram.

The feed is a discovery aid, not an editorial fact checker. Posts retain the
publisher link and should be reviewed by the channel editors after publication.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import html
from html.parser import HTMLParser
import json
import os
import re
import sys
from email.utils import parsedate_to_datetime
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
        if group.get("id") in {"regions", "ilken-evenki"}:
            continue
        for value in group.get("queries", []):
            term = str(value).strip()
            if term and term.casefold() not in excluded and term not in terms:
                terms.append(term)
    if not terms:
        raise ValueError("No usable queries found in news-search-queries.json")
    return terms


def load_ilken_queries() -> list[str]:
    data = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    for group in data.get("queryGroups", []):
        if group.get("id") == "ilken-evenki":
            return [str(value).strip().strip('"') for value in group.get("queries", []) if str(value).strip()]
    return []


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
        parsed = parsedate_to_datetime(value.strip())
        return (parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed).astimezone(TZ)
    except (TypeError, ValueError, OverflowError):
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


def fetch_ilken_feed() -> list[dict[str, str]]:
    """Read Ilken's Evenki news category, falling back from RSS to its archive page."""
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    feeds = [feed for feed in data.get("directFeeds", []) if feed.get("id") == "ilken-evenki-news"]
    found: list[dict[str, str]] = []
    cutoff = now_local() - dt.timedelta(days=MAX_SEEN_DAYS)
    for feed in feeds:
        try:
            root = ET.fromstring(request(str(feed["url"])))
            for node in root.findall("./channel/item"):
                title = clean(node.findtext("title", ""))
                description = clean(node.findtext("description", ""))
                link = clean(node.findtext("link", ""))
                published = parse_date(node.findtext("pubDate", ""))
                if not title or not link.startswith("https://ilken.ru/evenki/") or not published or published < cutoff:
                    continue
                guid = clean(node.findtext("guid", ""))
                found.append({
                    "id": guid or link, "title": title, "source": "Илкэн · Улгур",
                    "url": link, "published": published.isoformat(timespec="minutes"),
                    "day": published.date().isoformat(), "description": description,
                    "ilkenEvenki": "1",
                })
        except (urllib.error.URLError, TimeoutError, ET.ParseError, KeyError) as error:
            print(f"Warning: direct RSS failed for {feed.get('label', 'source')}: {error}", file=sys.stderr)

        # The publisher's RSS is currently returning HTTP 555 to GitHub Actions.
        # The category HTML is public and includes each story's date in its permalink.
        if not found and feed.get("category"):
            try:
                page = request(str(feed["category"]), headers={
                    "User-Agent": "Mozilla/5.0 (compatible; TaezhnayaNit-NewsMonitor/1.0)",
                    "Accept": "text/html,application/xhtml+xml",
                }).decode("utf-8", errors="replace")
                for story in IlkenCategoryParser().parse(page):
                    published = story["published"]
                    if published < cutoff:
                        continue
                    found.append({
                        "id": story["url"], "title": story["title"], "source": "Илкэн · Улгур",
                        "url": story["url"], "published": published.isoformat(timespec="minutes"),
                        "day": published.date().isoformat(), "description": story["description"],
                        "ilkenEvenki": "1",
                    })
                if found:
                    print(f"Read {len(found)} recent stories from the Ilken category page.")
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as error:
                print(f"Warning: Ilken category page failed: {error}", file=sys.stderr)

        # Ilken's origin also blocks GitHub Actions from its public HTML page.
        # Jina Reader fetches that public page and returns its article cards as Markdown.
        if not found and feed.get("category"):
            try:
                reader_url = "https://r.jina.ai/" + str(feed["category"])
                markdown = request(reader_url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; TaezhnayaNit-NewsMonitor/1.0)",
                    "Accept": "text/plain",
                }).decode("utf-8", errors="replace")
                for story in parse_ilken_reader_markdown(markdown):
                    published = story["published"]
                    if published < cutoff:
                        continue
                    found.append({
                        "id": story["url"], "title": story["title"], "source": "Илкэн · Улгур",
                        "url": story["url"], "published": published.isoformat(timespec="minutes"),
                        "day": published.date().isoformat(), "description": story["description"],
                        "ilkenEvenki": "1",
                    })
                if found:
                    print(f"Read {len(found)} recent stories from the Ilken category via Reader fallback.")
                else:
                    print("Warning: Reader fallback returned no recent Ilken category stories.", file=sys.stderr)
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as error:
                print(f"Warning: Ilken Reader fallback failed: {error}", file=sys.stderr)
    return found


class IlkenCategoryParser(HTMLParser):
    """Extract article cards from the visible WordPress category archive."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, object]] = []
        self._card_depth = 0
        self._card: dict[str, object] | None = None
        self._anchors: list[str] = []
        self._title_depth = 0
        self._description_depth = 0

    def parse(self, document: str) -> list[dict[str, object]]:
        self.feed(document)
        return [
            {
                **card,
                "title": clean(str(card.get("title", ""))),
                "description": clean(str(card.get("description", ""))),
                "published": published,
            }
            for card in self.cards
            if (published := ilken_permalink_date(str(card.get("url", "")))) is not None
            and card.get("title") and str(card.get("url", "")).startswith("https://ilken.ru/evenki/")
        ]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div" and self._card is None and "grid_post_content" in classes:
            self._card_depth = 1
            self._card = {"url": "", "title": "", "description": ""}
            self._anchors = []
            return
        if self._card is None:
            return
        if tag == "div":
            self._card_depth += 1
        if tag == "a":
            self._anchors.append(attributes.get("href") or "")
        if tag == "h4" and "b_title" in classes:
            self._title_depth = 1
            self._card["url"] = self._anchors[-1] if self._anchors else ""
        elif self._title_depth and tag == "h4":
            self._title_depth += 1
        if tag == "p":
            self._description_depth = 1
        elif self._description_depth and tag == "p":
            self._description_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag == "h4" and self._title_depth:
            self._title_depth -= 1
        if tag == "p" and self._description_depth:
            self._description_depth -= 1
        if tag == "a" and self._anchors:
            self._anchors.pop()
        if tag == "div":
            self._card_depth -= 1
            if self._card_depth == 0:
                self.cards.append(self._card)
                self._card = None

    def handle_data(self, data: str) -> None:
        if self._card is None:
            return
        if self._title_depth:
            self._card["title"] = str(self._card["title"]) + data
        if self._description_depth:
            self._card["description"] = str(self._card["description"]) + data


def ilken_permalink_date(url: str) -> dt.datetime | None:
    match = re.search(r"/evenki/(\d{4})/(\d{2})/(\d{2})/", url)
    if not match:
        return None
    try:
        return dt.datetime(*(int(part) for part in match.groups()), tzinfo=TZ)
    except ValueError:
        return None


def parse_ilken_reader_markdown(document: str) -> list[dict[str, object]]:
    """Extract article cards from Jina Reader's Markdown rendering of Ilken."""
    pattern = re.compile(
        r'^####\s+\[(?P<title>[^\]]+)\]\('
        r'(?P<url>https://ilken\.ru/evenki/\d{4}/\d{2}/\d{2}/[^\s)]+)'
        r'(?:\s+"[^"]*")?\)\s*\n'
        r'(?P<description>.*?)(?=\n(?:####\s|!\[|\[[^\]]+\]\(https://ilken\.ru/evenki/)|\Z)',
        flags=re.MULTILINE | re.DOTALL,
    )
    stories: list[dict[str, object]] = []
    for match in pattern.finditer(document):
        url = match.group("url")
        published = ilken_permalink_date(url)
        if not published:
            continue
        stories.append({
            "url": url,
            "title": clean(match.group("title")),
            "description": clean(match.group("description"))[:420],
            "published": published,
        })
    return stories


def fetch_items() -> list[dict[str, str]]:
    terms = load_queries()
    query = " OR ".join(f'"{term.strip(chr(34))}"' for term in terms)
    domains = load_source_domains()
    domain_groups = [domains[i:i + 12] for i in range(0, len(domains), 12)]
    feeds = [(f"({query}) when:2d", False)]
    for group in domain_groups:
        sites = " OR ".join(f"site:{domain}" for domain in group)
        feeds.append((f"({query}) ({sites}) when:2d", False))
    ilken_terms = load_ilken_queries()
    # Keep a source-wide fallback: Evenki-language headlines do not always
    # contain the same orthographic markers or the words chosen as search terms.
    feeds.append(("site:ilken.ru/evenki/ when:30d", True))
    feeds.extend((f'site:ilken.ru/evenki/ "{term}" when:30d', True) for term in ilken_terms)
    items: list[dict[str, str]] = []
    cutoff = now_local() - dt.timedelta(hours=LOOKBACK_HOURS)
    failures = 0
    for feed_query, ilken_search in feeds:
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
            published = parse_date(node.findtext("pubDate", ""))
            if not published or published < cutoff:
                continue
            link = clean(node.findtext("link", ""))
            if not link.startswith("https://"):
                continue
            source_node = node.find("source")
            source = clean(source_node.text if source_node is not None else "")
            source_host = ""
            if source_node is not None:
                source_host = (urllib.parse.urlsplit(source_node.attrib.get("url", "")).hostname or "").lower()
            guid = clean(node.findtext("guid", ""))
            item_id = guid or link
            publisher_url = original_source_url(link)
            is_ilken = ilken_search and publisher_url.startswith("https://ilken.ru/evenki/")
            publisher_host = (urllib.parse.urlsplit(publisher_url).hostname or "").lower()
            configured_source = any(
                host == domain or host.endswith("." + domain)
                for host in (source_host, publisher_host)
                for domain in domains
            ) and "news.google.com" not in publisher_host
            if not CORE_RE.search(f"{title} {description}") and not is_ilken:
                continue
            items.append({
                "id": item_id,
                "title": title,
                "source": source or "Источник в Google Новостях",
                "url": publisher_url,
                "published": published.isoformat(timespec="minutes"),
                "day": published.date().isoformat(),
                "description": description,
                "ilkenEvenki": "1" if is_ilken else "0",
                "configuredSource": "1" if configured_source else "0",
            })
    direct_items = fetch_ilken_feed()
    if failures == len(feeds) and not direct_items:
        raise RuntimeError("All Google News RSS searches failed")
    # Deduplicate repeated variants within a single RSS response.
    return list({item["url"].rstrip("/"): item for item in items + direct_items}.values())


def update_site_news_feed(items: list[dict[str, str]]) -> int:
    """Append matching results from configured media and Ilken's Evenki posts."""
    candidates = [item for item in items if item.get("siteEligible") == "1"]
    path = ROOT / "news-data.js"
    text = path.read_text(encoding="utf-8")
    body = text[text.find("[") + 1:text.rfind("]")]
    stories = []
    for match in re.findall(r"\{[^{}]*\}", body):
        js_object = re.sub(r"([{,]\s*)([A-Za-z][A-Za-z0-9]*)(\s*:)", r"\1'\2'\3", match)
        try:
            stories.append(ast.literal_eval(js_object))
        except (ValueError, SyntaxError):
            continue
    known = {str(story.get("link", "")).rstrip("/") for story in stories}
    added = 0
    for item in candidates:
        link = item["url"].rstrip("/")
        if link in known:
            continue
        stories.append({
            "region": item.get("region") or "Федеральные и общие",
            "date": item["day"], "source": item["source"],
            "title": item["title"],
            "desc": (item.get("description") or "Публикация о жизни, языке или культуре эвенков. Читайте оригинал в СМИ.")[:420],
            "tags": "эвенки эвенкийский язык новости", "link": item["url"],
        })
        known.add(link)
        added += 1
    if added:
        stories.sort(key=lambda story: str(story.get("date", "")), reverse=True)
        path.write_text("window.newsStories=" + json.dumps(stories, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    return added


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
    # Search results from configured publishers are added to the general feed;
    # Ilken's dedicated Evenki-language category is a trusted direct-source feed.
    for item in found:
        item["siteEligible"] = "1" if item.get("ilkenEvenki") == "1" or item.get("configuredSource") == "1" else "0"
    new_site_stories = update_site_news_feed(found) if args.mode == "collect" else 0
    if new_site_stories:
        print(f"Added {new_site_stories} new stories to the website news feed.")
    unseen_today = [item for item in found if item["day"] == today and item["id"] not in state["seen"]]

    # Expire IDs older than a month and old digest buckets.
    expiry = now_local() - dt.timedelta(days=MAX_SEEN_DAYS)
    state["seen"] = {
        key: value for key, value in state["seen"].items()
        if (parse_date(value) or now_local()) >= expiry
    }
    state["daily"] = {day: items for day, items in state["daily"].items() if day >= (now_local().date() - dt.timedelta(days=7)).isoformat()}

    if args.mode == "collect":
        # On the first successful scrape, send recent Ilken posts as a catch-up
        # even when they were published before today. Other sources stay today-only.
        to_post = [
            item for item in found
            if item["id"] not in state["seen"]
            and (item["day"] == today or item.get("ilkenEvenki") == "1")
        ]
        for item in to_post:
            telegram_send(format_item(item))
            state["seen"][item["id"]] = now_local().isoformat(timespec="minutes")
            state["daily"].setdefault(item["day"], []).append(item)
            save_state(state)
        # Remember older search results too, so they do not reappear on every run.
        for item in found:
            if item["day"] != today and item.get("ilkenEvenki") != "1":
                state["seen"].setdefault(item["id"], now_local().isoformat(timespec="minutes"))
        print(f"Fetched {len(found)} candidates; posted {len(to_post)} new items ({len(unseen_today)} dated today).")
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

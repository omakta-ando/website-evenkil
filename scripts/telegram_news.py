#!/usr/bin/env python3
"""Collect recent Evenki-related headlines from Google News RSS and post to Telegram.

The feed is a discovery aid, not an editorial fact checker. Posts retain the
publisher link and should be reviewed by the channel editors after publication.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import ast
import datetime as dt
import html
from html.parser import HTMLParser
import json
import os
import re
import sys
import time
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
LOOKBACK_HOURS = 72
MAX_SEEN_DAYS = 30
MAX_DIGEST_ITEMS = 40

CORE_RE = re.compile(r"эвенк|эвенки|эвенкий|эвенкия|эвенкил|эвэды|ороч[её]н|хамниган|манегр|бирар|солон|бакалдын|мучун", re.I)
EXCLUDED_TOPIC_RE = re.compile(r"(?:нанайск\w*.{0,50}шашк\w*|шашк\w*.{0,50}нанайск\w*)", re.I)
EXCLUDED_STORY_URLS = {"https://t.me/biraria/4194"}


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


def load_query_group(group_id: str) -> list[str]:
    data = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    for group in data.get("queryGroups", []):
        if group.get("id") == group_id:
            return [str(value).strip() for value in group.get("queries", []) if str(value).strip()]
    return []


def load_social_search_sites() -> list[str]:
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    sites = [str(account.get("googleNewsSite", "")).strip() for account in data.get("socialAccounts", [])]
    return [site for site in sites if re.fullmatch(r"[a-z0-9.-]+/[a-zA-Z0-9_./-]+", site)]


def load_source_domains() -> list[str]:
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    domains = [str(value).strip().lower() for value in data.get("domains", [])]
    domains = [value for value in domains if re.fullmatch(r"[a-z0-9.-]+|[^\s/]+", value)]
    if not domains:
        raise ValueError("No source domains found in news-search-sources.json")
    return domains


def request(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 25) -> bytes:
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "TaezhnayaNit-NewsMonitor/1.0 (RSS reader)"} | (headers or {}),
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
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


def parse_russian_publication_date(value: str) -> dt.datetime | None:
    months = {
        "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
        "мая": 5, "июня": 6, "июля": 7, "августа": 8,
        "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    }
    match = re.search(r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})\b", clean(value).casefold())
    if not match or match.group(2) not in months:
        return None
    try:
        return dt.datetime(int(match.group(3)), months[match.group(2)], int(match.group(1)), tzinfo=TZ)
    except ValueError:
        return None


def fetch_arun_news() -> list[dict[str, str]]:
    """Read every dated, recent article from the Evenki culture center archive."""
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    feed = next((item for item in data.get("directFeeds", []) if item.get("id") == "arun-news"), None)
    if not feed:
        return []
    category_url = str(feed.get("category", "")).strip()
    if not category_url:
        return []
    try:
        document = request(category_url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; TaezhnayaNit-NewsMonitor/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        }).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"Warning: Арун news archive failed: {error}", file=sys.stderr)
        return []

    cutoff = now_local() - dt.timedelta(days=MAX_SEEN_DAYS)
    found: list[dict[str, str]] = []
    for story in ArunNewsParser().parse(document, category_url):
        published = story["published"]
        if published.date() < cutoff.date() or published > now_local() + dt.timedelta(days=1):
            continue
        url = str(story["url"])
        title = clean(str(story["title"]))
        description = clean(str(story["description"]))
        searchable = f"{title} {description}".casefold()
        region = "Общие новости"
        if any(term in searchable for term in ("бурят", "улан-удэ", "курумкан", "баунт", "алле", "багдарин")):
            region = "Бурятия"
        elif any(term in searchable for term in ("чите", "забайкал", "каларск")):
            region = "Забайкальский край"
        found.append({
            "id": url,
            "title": title,
            "source": "Центр эвенкийской культуры «Арун»",
            "url": url,
            "published": published.isoformat(timespec="minutes"),
            "day": published.date().isoformat(),
            "description": description,
            "arunNews": "1",
            "configuredSource": "1",
            "region": region,
        })
    print(f"Read {len(found)} recent dated publications from the Арун news archive.")
    return found


class ArunNewsParser(HTMLParser):
    """Extract title, blurb, date and canonical link from Arуn's archive cards."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, object]] = []
        self.card: dict[str, object] | None = None
        self.card_depth = 0
        self.mode: str | None = None

    def parse(self, document: str, base_url: str) -> list[dict[str, object]]:
        self.feed(document)
        result: list[dict[str, object]] = []
        for card in self.cards:
            published = parse_russian_publication_date(str(card.get("date", "")))
            raw_url = str(card.get("url", "")).strip()
            if not published or not card.get("title") or not raw_url:
                continue
            url = urllib.parse.urljoin(base_url, raw_url)
            if not url.startswith("https://arun-rb.ru/"):
                continue
            parsed_url = urllib.parse.urlsplit(url)
            # The archive's relative hrefs resolve below /novosti/, but the
            # publisher's canonical article URLs are at the domain root.
            path = parsed_url.path
            if path.startswith("/novosti/"):
                path = "/" + path.removeprefix("/novosti/")
            url = urllib.parse.urlunsplit((parsed_url.scheme, parsed_url.netloc, path, parsed_url.query, parsed_url.fragment))
            url = urllib.parse.quote(url, safe=":/%?=&")
            result.append({
                "url": url,
                "title": clean(str(card.get("title", ""))),
                "description": clean(str(card.get("description", "")))[:420],
                "published": published,
            })
        return result

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div" and "category-item__right" in classes and self.card is None:
            self.card = {"url": "", "title": "", "description": "", "date": ""}
            self.card_depth = 1
            self.mode = None
            return
        if self.card is None:
            return
        if tag == "div":
            self.card_depth += 1
            if "category-item__intro" in classes:
                self.mode = "description"
            elif "category-item__date" in classes:
                self.mode = "date"
        elif tag == "h3" and "category-item__title" in classes:
            self.mode = "title"
        elif tag == "a" and self.mode == "title":
            self.card["url"] = attributes.get("href") or ""

    def handle_endtag(self, tag: str) -> None:
        if self.card is None:
            return
        if tag == "h3" and self.mode == "title":
            self.mode = None
        if tag == "div":
            self.card_depth -= 1
            if self.card_depth <= 0:
                self.cards.append(self.card)
                self.card = None
                self.card_depth = 0
                self.mode = None

    def handle_data(self, data: str) -> None:
        if self.card is None or not self.mode:
            return
        key = {"title": "title", "description": "description", "date": "date"}.get(self.mode)
        if key:
            self.card[key] = str(self.card[key]) + data


def fetch_ilken_feed() -> list[dict[str, str]]:
    """Read Ilken's Evenki category and the main multilingual news feed."""
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    feeds = [feed for feed in data.get("directFeeds", []) if feed.get("id") in {"ilken-evenki-news", "ilken-russian-news"}]
    found: list[dict[str, str]] = []
    cutoff = now_local() - dt.timedelta(days=MAX_SEEN_DAYS)
    for feed in feeds:
        is_evenki_feed = feed.get("id") == "ilken-evenki-news"
        feed_start = len(found)
        feed_cutoff = cutoff if is_evenki_feed else now_local() - dt.timedelta(hours=LOOKBACK_HOURS)
        try:
            root = ET.fromstring(request(str(feed["url"])))
            for node in root.findall("./channel/item"):
                title = clean(node.findtext("title", ""))
                description = clean(node.findtext("description", ""))
                link = clean(node.findtext("link", ""))
                published = parse_date(node.findtext("pubDate", ""))
                valid_link = link.startswith("https://ilken.ru/evenki/") if is_evenki_feed else (
                    link.startswith("https://ilken.ru/") and "/evenki/" not in link
                )
                if not title or not valid_link or not published or published < feed_cutoff:
                    continue
                if not is_evenki_feed and not CORE_RE.search(f"{title} {description}"):
                    continue
                guid = clean(node.findtext("guid", ""))
                found.append({
                    "id": guid or link, "title": title, "source": "Илкэн · Улгур",
                    "url": link, "published": published.isoformat(timespec="minutes"),
                    "day": published.date().isoformat(), "description": description,
                    "ilkenEvenki": "1" if is_evenki_feed else "0",
                    "configuredSource": "0" if is_evenki_feed else "1",
                })
        except (urllib.error.URLError, TimeoutError, ET.ParseError, KeyError) as error:
            print(f"Warning: direct RSS failed for {feed.get('label', 'source')}: {error}", file=sys.stderr)

        # The publisher's RSS is currently returning HTTP 555 to GitHub Actions.
        # The category HTML is public and includes each story's date in its permalink.
        if len(found) == feed_start and feed.get("category"):
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
        if len(found) == feed_start and feed.get("category"):
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


class TelegramPublicChannelParser(HTMLParser):
    """Extract recent text posts from Telegram's public channel preview."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.posts: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.container_depth = 0
        self.capture_text = False
        self.text_div_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div":
            if self.current is None and "tgme_widget_message_wrap" in classes:
                self.current = {"post": "", "url": "", "date": "", "text": "", "image": ""}
                self.container_depth = 1
            elif self.current is not None:
                self.container_depth += 1
            if self.current is not None and "data-post" in attributes:
                self.current["post"] = attributes.get("data-post") or ""
            if self.current is not None and classes.intersection({"tgme_widget_message_photo", "tgme_widget_message_video_thumb"}):
                style = attributes.get("style") or ""
                image = re.search(r"background-image\s*:\s*url\(['\"]?(.*?)['\"]?\)", style, re.I)
                if image:
                    self.current["image"] = html.unescape(image.group(1))
            if self.current is not None and "tgme_widget_message_text" in classes:
                self.capture_text = True
                self.text_div_depth = 1
        elif self.current is not None:
            if tag == "img" and not self.current.get("image"):
                self.current["image"] = attributes.get("src") or ""
            if self.capture_text and tag == "br":
                self.current["text"] += " "
            if tag == "a" and "tgme_widget_message_date" in classes:
                self.current["url"] = attributes.get("href") or ""
            elif tag == "time":
                self.current["date"] = attributes.get("datetime") or ""

    def handle_endtag(self, tag: str) -> None:
        if self.current is None or tag != "div":
            return
        if self.capture_text:
            self.text_div_depth -= 1
            if self.text_div_depth <= 0:
                self.capture_text = False
        self.container_depth -= 1
        if self.container_depth <= 0:
            if self.current.get("post") or self.current.get("url"):
                self.posts.append(self.current)
            self.current = None
            self.container_depth = 0
            self.capture_text = False

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.capture_text:
            self.current["text"] += data


def fetch_telegram_public_channels() -> list[dict[str, str]]:
    """Read public posts directly; Google News remains as a discovery fallback."""
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    cutoff = now_local() - dt.timedelta(hours=LOOKBACK_HOURS)
    found: list[dict[str, str]] = []
    for account in data.get("socialAccounts", []):
        url = str(account.get("url", "")).strip()
        parsed = urllib.parse.urlsplit(url)
        if parsed.hostname not in {"t.me", "telegram.me"}:
            continue
        username = parsed.path.strip("/").split("/")[0]
        if not re.fullmatch(r"[A-Za-z0-9_]+", username):
            continue
        try:
            page = request(
                f"https://t.me/s/{username}",
                headers={"User-Agent": "Mozilla/5.0 (compatible; TaezhnayaNit-NewsMonitor/1.0)",
                         "Accept": "text/html,application/xhtml+xml"},
                timeout=20,
            ).decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"Warning: Telegram public channel unavailable ({account.get('label', username)}): {error}", file=sys.stderr)
            continue
        parser = TelegramPublicChannelParser()
        parser.feed(page)
        for post in parser.posts:
            published = parse_date(post.get("date", ""))
            text = clean(post.get("text", ""))
            if not published or published < cutoff or not CORE_RE.search(text):
                continue
            post_path = post.get("post", "").strip("/")
            post_url = f"https://t.me/{post_path}" if post_path else post.get("url", "")
            if not post_url.startswith("https://t.me/"):
                continue
            found.append({
                "id": post_url,
                "title": text[:180].rstrip(" .…") or str(account.get("label", "Telegram")),
                "source": str(account.get("label", "Telegram")),
                "url": post_url,
                "published": published.isoformat(timespec="minutes"),
                "day": published.date().isoformat(),
                "description": text[:420],
                "socialPlatform": "Telegram",
                "configuredSource": "1",
                **({"image": post["image"]} if post.get("image") else {}),
            })
    print(f"Read {len(found)} recent relevant posts directly from public Telegram channels.")
    return found


def fetch_vk_public_walls() -> list[dict[str, str]]:
    """Read configured public VK walls through the official API when configured."""
    token = os.environ.get("VK_ACCESS_TOKEN", "").strip()
    if not token:
        print("VK direct wall reading is off; set the GitHub Actions secret VK_ACCESS_TOKEN to enable it.")
        return []
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    cutoff = now_local() - dt.timedelta(hours=LOOKBACK_HOURS)
    found: list[dict[str, str]] = []
    for account in data.get("socialAccounts", []):
        parsed = urllib.parse.urlsplit(str(account.get("url", "")))
        if parsed.hostname not in {"vk.com", "vk.ru", "www.vk.com", "www.vk.ru"}:
            continue
        domain = parsed.path.strip("/").split("/")[0]
        if not domain:
            continue
        params = urllib.parse.urlencode({
            "domain": domain, "count": 100, "filter": "owner",
            "access_token": token, "v": "5.199",
        }).encode("utf-8")
        try:
            payload = request(
                "https://api.vk.com/method/wall.get",
                data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=20,
            )
            result = json.loads(payload)
            if result.get("error"):
                error_code = result["error"].get("error_code", "unknown")
                print(f"Warning: VK API rejected {account.get('label', domain)} (error {error_code}).", file=sys.stderr)
                continue
            posts = result.get("response", {}).get("items", [])
        except (urllib.error.URLError, TimeoutError, ValueError, AttributeError) as error:
            print(f"Warning: VK wall unavailable ({account.get('label', domain)}): {error}", file=sys.stderr)
            continue
        for post in posts:
            text = clean(str(post.get("text", "")))
            published = dt.datetime.fromtimestamp(int(post.get("date", 0)), tz=TZ)
            if published < cutoff or not CORE_RE.search(text):
                continue
            owner_id = int(post.get("owner_id", 0))
            post_id = int(post.get("id", 0))
            post_url = f"https://vk.com/wall{owner_id}_{post_id}"
            found.append({
                "id": post_url,
                "title": text[:180].rstrip(" .…") or str(account.get("label", "ВКонтакте")),
                "source": str(account.get("label", "ВКонтакте")),
                "url": post_url,
                "published": published.isoformat(timespec="minutes"),
                "day": published.date().isoformat(),
                "description": text[:420],
                "socialPlatform": "ВКонтакте",
                "configuredSource": "1",
            })
    print(f"Read {len(found)} recent relevant posts directly from configured VK walls.")
    return found


def fetch_items() -> list[dict[str, str]]:
    domains = load_source_domains()

    # Search the full Google News index in focused topic groups. Keeping these
    # separate avoids one oversized OR query losing narrower language/culture hits.
    feeds: list[tuple[str, bool]] = []
    for group_id in ("core", "language-education", "culture", "historical-and-local-names"):
        terms = load_query_group(group_id)
        if terms:
            query = " OR ".join(f'"{term.strip(chr(34))}"' for term in terms)
            feeds.append((f"({query}) when:2d", False))

    # Search every configured publisher separately. Combining many sites into
    # one Google News query can crowd out smaller outlets in the RSS results.
    source_terms = (
        "эвенки", "эвенк", "эвенкийский", "эвенкия", "эвенкил", "эвэды",
        "орочон", "орочёны", "хамниган", "тунгус", "бирар", "манегр",
        "солон", "бакалдын", "мучун",
    )
    source_query = " OR ".join(f'"{term}"' for term in source_terms)
    feeds.extend((f"site:{domain} ({source_query}) when:2d", False) for domain in domains)

    local_terms = load_query_group("eao-evenki")
    if local_terms:
        local_query = " OR ".join(f'"{term.strip(chr(34))}"' for term in local_terms)
        feeds.append((f"({local_query}) when:30d", False))

    # Search every configured public social account across all major topic groups,
    # not only the regional EAO terms. Google News provides public index coverage;
    # direct access to private posts or unindexed content requires platform APIs.
    social_sites = load_social_search_sites()
    for group_id in ("core", "language-education", "culture", "historical-and-local-names", "eao-evenki"):
        terms = load_query_group(group_id)
        if not terms:
            continue
        social_query = " OR ".join(f'"{term.strip(chr(34))}"' for term in terms)
        feeds.extend((f"site:{site} ({social_query}) when:7d", False) for site in social_sites)
    ilken_terms = load_ilken_queries()
    # Keep source-wide searches for the dedicated Ilken Evenki category.
    feeds.append(("site:ilken.ru/evenki/ when:30d", True))
    feeds.extend((f'site:ilken.ru/evenki/ "{term}" when:30d', True) for term in ilken_terms)
    feeds.append(("site:ilken.ru when:2d", False))

    cutoff = now_local() - dt.timedelta(hours=LOOKBACK_HOURS)

    def search_feed(feed: tuple[str, bool]) -> tuple[list[dict[str, str]], str | None]:
        feed_query, ilken_search = feed
        params = urllib.parse.urlencode({"q": feed_query, "hl": "ru", "gl": "RU", "ceid": "RU:ru"})
        try:
            payload = request(f"{RSS_URL}?{params}")
            root = ET.fromstring(payload)
        except (urllib.error.URLError, TimeoutError, ET.ParseError) as error:
            return [], str(error)

        found: list[dict[str, str]] = []
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
            found.append({
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
        return found, None

    items: list[dict[str, str]] = []
    failures = 0
    # Keep the run short while spreading requests so no source group monopolizes
    # the limited number of results returned by Google News RSS.
    with ThreadPoolExecutor(max_workers=6) as executor:
        for found, error in executor.map(search_feed, feeds):
            if error:
                failures += 1
                print(f"Warning: one RSS search failed: {error}", file=sys.stderr)
            items.extend(found)

    direct_items = fetch_ilken_feed() + fetch_arun_news() + fetch_telegram_public_channels() + fetch_vk_public_walls()
    if failures == len(feeds) and not direct_items:
        raise RuntimeError("All Google News RSS searches failed")
    # Deduplicate repeated articles returned by the global and publisher-specific searches.
    candidates = items + direct_items
    excluded = [
        item for item in candidates
        if item.get("url", "").rstrip("/") in EXCLUDED_STORY_URLS
        or EXCLUDED_TOPIC_RE.search(f"{item.get('title', '')} {item.get('description', '')}")
    ]
    if excluded:
        print(f"Excluded {len(excluded)} stories by editorial filters.")
    return list({item["url"].rstrip("/"): item for item in candidates if item not in excluded}.values())


def update_site_news_feed(items: list[dict[str, str]]) -> int:
    """Append matching results from configured media and Ilken's Evenki posts."""
    candidates = [item for item in items if item.get("siteEligible") == "1"]
    path = ROOT / "news-data.js"
    stories = load_site_news_stories()
    known = {str(story.get("link", "")).rstrip("/") for story in stories}
    added = 0
    for item in candidates:
        link = item["url"].rstrip("/")
        if link in known:
            continue
        category = "Новости на эвенкийском" if item.get("ilkenEvenki") == "1" else "Общие новости"
        stories.append({
            "region": item.get("region") or category,
            "date": item["day"], "source": item["source"],
            "title": item["title"],
            "desc": (item.get("description") or "Публикация о жизни, языке или культуре эвенков. Читайте оригинал в СМИ.")[:420],
            "tags": "эвенки эвенкийский язык новости", "link": item["url"],
            **({"image": item["image"]} if item.get("image") else {}),
        })
        known.add(link)
        added += 1
    if added:
        stories.sort(key=lambda story: str(story.get("date", "")), reverse=True)
        path.write_text("window.newsStories=" + json.dumps(stories, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    return added


def load_site_news_stories() -> list[dict[str, object]]:
    text = (ROOT / "news-data.js").read_text(encoding="utf-8")
    body = text[text.find("[") + 1:text.rfind("]")]
    stories = []
    for match in re.findall(r"\{[^{}]*\}", body):
        js_object = re.sub(r"([{,]\s*)([A-Za-z][A-Za-z0-9]*)(\s*:)", r"\1'\2'\3", match)
        try:
            stories.append(ast.literal_eval(js_object))
        except (ValueError, SyntaxError):
            continue
    return stories


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {"version": 1, "seen": {}, "daily": {}}
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("Unsupported Telegram news state format")
    state.setdefault("seen", {})
    state.setdefault("daily", {})
    state.setdefault("pendingTelegram", [])
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
    body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, ensure_ascii=False).encode("utf-8")
    result = json.loads(request(url, data=body, headers={"Content-Type": "application/json"}))
    if not result.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {result.get('description', 'unknown error')}")


def telegram_send_item(item: dict[str, str]) -> None:
    """Send a story with its site image when available, otherwise as text."""
    image = item.get("image", "").strip()
    if not image:
        telegram_send(format_item(item))
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "@taiga_thread").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured in GitHub Actions secrets")
    url = f"{BOT_API}/bot{token}/sendPhoto"
    body = json.dumps({
        "chat_id": chat_id,
        "photo": image,
        "caption": format_item(item),
        "parse_mode": "HTML",
    }, ensure_ascii=False).encode("utf-8")
    result = json.loads(request(url, data=body, headers={"Content-Type": "application/json"}))
    if not result.get("ok"):
        print(f"Telegram could not attach image for {item.get('url')}; sending text instead: {result.get('description', 'unknown error')}", file=sys.stderr)
        telegram_send(format_item(item))


def format_item(item: dict[str, str], number: int | None = None) -> str:
    prefix = f"{number}. " if number is not None else "📰 "
    title = html.escape(clean(item.get("title", "")))
    url = html.escape(item.get("url", ""), quote=True)
    description = clean(item.get("description", ""))
    # Keep title and summary as plain text; link only the source name.
    if len(description) > 420:
        description = description[:417].rsplit(" ", 1)[0] + "…"
    lines = [f"{prefix}{title}"]
    if description:
        lines.append(html.escape(description))
    lines.append(f"<a href=\"{url}\">{html.escape(item['source'])}</a> · {html.escape(item['published'][:10])}")
    return "\n".join(lines)


def send_digest(today: str, state: dict) -> None:
    items = state["daily"].get(today, [])
    if not items:
        print(f"No matching stories for {today}; digest skipped.")
        return
    selected = items[:MAX_DIGEST_ITEMS]
    parts = [f"📰 Что произошло сегодня — {today}"]
    for index, item in enumerate(selected, start=1):
        parts.append(format_item(item, number=index))
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


def wait_for_site_publication(items: list[dict[str, str]]) -> None:
    """Do not notify Telegram until GitHub Pages serves every story in the feed."""
    if not items:
        return
    public_feed = "https://omakta-ando.github.io/website-evenkil/news-data.js"
    expected = [item["url"].rstrip("/") for item in items]
    for attempt in range(20):
        try:
            url = f"{public_feed}?publish_check={int(time.time())}-{attempt}"
            published = request(url, timeout=12).decode("utf-8", errors="replace")
            if all(link in published for link in expected):
                print(f"Confirmed {len(expected)} stories are live on the website.")
                return
        except (urllib.error.URLError, TimeoutError):
            pass
        if attempt < 19:
            time.sleep(15)
    raise RuntimeError("GitHub Pages has not published the queued stories; Telegram posting was held back.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("collect", "notify", "digest"), default="collect")
    args = parser.parse_args()

    today = now_local().date().isoformat()
    state = read_state()
    if args.mode == "notify":
        pending = list(state.get("pendingTelegram", []))
        if not pending:
            print("No newly published stories are waiting for Telegram.")
            return 0
        wait_for_site_publication(pending)
        site_images = {
            str(story.get("link", "")).rstrip("/"): str(story.get("image", "")).strip()
            for story in load_site_news_stories()
            if story.get("image")
        }
        sent = 0
        for item in pending:
            item_with_image = dict(item)
            item_with_image["image"] = item.get("image") or site_images.get(str(item.get("url", "")).rstrip("/"), "")
            telegram_send_item(item_with_image)
            state["seen"][item["id"]] = now_local().isoformat(timespec="minutes")
            state["daily"].setdefault(item["day"], []).append(item)
            state["pendingTelegram"].remove(item)
            save_state(state)
            sent += 1
        print(f"Posted {sent} site-published stories to Telegram.")
        return 0

    if args.mode == "digest":
        send_digest(today, state)
        return 0

    found = fetch_items()
    # Search results from configured publishers are added to the general feed;
    # Ilken's dedicated Evenki-language category is a trusted direct-source feed.
    for item in found:
        item["siteEligible"] = "1" if item.get("ilkenEvenki") == "1" or item.get("arunNews") == "1" or item.get("configuredSource") == "1" else "0"
    new_site_stories = update_site_news_feed(found) if args.mode == "collect" else 0
    if new_site_stories:
        print(f"Added {new_site_stories} new stories to the website news feed.")
    # Expire IDs older than a month and old digest buckets.
    expiry = now_local() - dt.timedelta(days=MAX_SEEN_DAYS)
    state["seen"] = {
        key: value for key, value in state["seen"].items()
        if (parse_date(value) or now_local()) >= expiry
    }
    state["daily"] = {day: items for day, items in state["daily"].items() if day >= (now_local().date() - dt.timedelta(days=7)).isoformat()}

    public_links = {str(story.get("link", "")).rstrip("/") for story in load_site_news_stories()}
    telegram_cutoff = now_local() - dt.timedelta(hours=LOOKBACK_HOURS)
    state["pendingTelegram"] = [
        item for item in state["pendingTelegram"]
        if (parse_date(item.get("published", "")) or now_local()) >= telegram_cutoff
    ]
    queued_ids = {item.get("id") for item in state["pendingTelegram"]}
    queued = [
        item for item in found
        if item.get("siteEligible") == "1"
        and (parse_date(item.get("published", "")) or now_local()) >= telegram_cutoff
        and item["url"].rstrip("/") in public_links
        and item["id"] not in state["seen"]
        and item["id"] not in queued_ids
    ]
    state["pendingTelegram"].extend(queued)
    print(f"Fetched {len(found)} candidates; added {new_site_stories} to the site and queued {len(queued)} for Telegram after publication.")

    save_state(state)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, ET.ParseError, OSError, ValueError, RuntimeError) as error:
        print(f"News collector failed: {error}", file=sys.stderr)
        raise SystemExit(1)

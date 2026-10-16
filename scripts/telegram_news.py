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
import news_sources

AUDIT = news_sources.Audit()
AUDIT_FILE = Path(__file__).resolve().parents[1] / "data" / "news-source-audit.json"


ROOT = Path(__file__).resolve().parents[1]
QUERIES_FILE = ROOT / "news-search-queries.json"
SOURCES_FILE = ROOT / "news-search-sources.json"
STATE_FILE = ROOT / "data" / "telegram-news-state.json"
TZ = ZoneInfo("Asia/Tbilisi")
RSS_URL = "https://news.google.com/rss/search"
BOT_API = "https://api.telegram.org"
LOOKBACK_HOURS = 7 * 24
MAX_SEEN_DAYS = 30
MAX_DIGEST_ITEMS = 40
MAX_TOPIC_STORIES_PER_REGION = 2
TOPIC_STORY_LOOKBACK_DAYS = 7
SUPPLY_ACTIVITY_RE = re.compile(r"(?:завоз\w*|снабжени\w*|доставк\w*|поставк\w*|перевозк\w*)", re.I)
SUPPLY_GOODS_RE = re.compile(r"(?:продукт\w*|топлив\w*|груз\w*|товар\w*|снабжени\w*)", re.I)
NORTH_SUPPLY_CONTEXT_RE = re.compile(
    r"(?:северн\w{0,12}|арктическ\w*|таймыр\w*|эвенки\w*|"
    r"отдал[её]нн\w*.{0,30}посел\w*|север\w*.{0,50}(?:красноярск\w*|саха|якут\w*)|"
    r"(?:красноярск\w*|саха|якут\w*).{0,50}север\w*)", re.I)
MAX_FULLTEXT_REVIEWS = 40
FULLTEXT_CANDIDATE_RE = re.compile(r"(?:олен\w*|оленевод\w*|экспорт\w*|ген[ьъ]?х[эе]\w*|тянск\w*|арктик\w*|северн\w*.{0,24}(?:завоз\w*|посел\w*|район\w*|народ\w*|олень\w*)|завоз\w*|снабжени\w*|груз\w*|коренн\w* народ\w*|общин\w*|традиц\w*|культур\w*|язык\w*|школ\w*|промысл\w*|охот\w*|рыболов\w*)", re.I)

EVENKI_MENTION_RE = re.compile(
    r"(?:\bэвенк(?:и|ов|ам|ами|ах|а|у|ом|е|ой|ою|ок)\b"
    r"|\b(?:ороч[её]н|хамниган|манегр|бакалдын|мучун)\w*\b|\bсолон(?:ы|ов|ам|ами|ах|а|у|ом|е|ск(?:ий|ая|ое|ие|их|им|ую|ого|ому|ыми))?\b"
    r"|\bбирар(?:ы|ов|ам|ами|ах|а|у|ом|е|ой|ою)\b"
    r"|\bэвенкийц\w*\b|\bперевод\w*\s+с\s+эвенкийск\w*\b|\bэвенкийск\w{0,16}\s+(?:язык\w*|культур\w*|реч\w*|словар\w*|песн\w*|музык\w*|танц\w*|фольклор\w*|литератур\w*|писател\w*|поэт\w*|композитор\w*|художник\w*|артист\w*|школ\w*|учебник\w*|обучен\w*|диктант\w*|олимпиад\w*|конкурс\w*|традиц\w*|обыча\w*|музе\w*|искусств\w*|общин\w*|обществ\w*|истори\w*|наслед\w*|оленевод\w*|промысл\w*|ансамбл\w*)"
    r"|\b(?:evenkis?|ewenkis?|orochons?|oroqens?|oroqins?|khamnigans?|hamnigans?)\b"
    r"|鄂温克|鄂伦春|鄂倫春|敖鲁古雅|エヴェンキ|オロチョン|ハムニガン|에벤키|오로촌|함니간)", re.I)
CONTEXT_TOPIC_RE = re.compile(
    r"(?:северн\w{0,12}\s+завоз\w*|завоз\w*.{0,40}северн\w*\s+(?:район\w*|посел\w*)|"
    r"арктическ\w{0,16}\s+(?:завоз\w*|снабжени\w*|доставк\w*)|"
    r"снабжени\w*.{0,50}(?:арктическ\w*|северн\w*|отдал[её]нн\w*) посел\w*|"
    r"доставк\w*.{0,50}(?:отдал[её]нн\w* северн\w*|северн\w* отдал[её]нн\w*) посел\w*|"
    r"(?:правил\w*.{0,35}охот\w*|охот\w*.{0,35}правил\w*|срок\w* охот\w*|сезон охот\w*|охотнич\w* сезон\w*|"
    r"закон\w*.{0,35}охот\w*|охот\w*.{0,35}закон\w*|измен\w*.{0,35}охот\w*|"
    r"правил\w*.{0,35}рыболов\w*|рыболов\w*.{0,35}правил\w*|измен\w*.{0,35}рыболов\w*|нерестов\w* запрет\w*|"
    r"квот\w*.{0,30}(?:вылов\w*|рыб\w*)|(?:вылов\w*|рыб\w*).{0,30}квот\w*|"
    r"оленевод\w*|оленеводческ\w*|пастбищ\w*.{0,35}олен\w*|олен\w*.{0,35}пастбищ\w*|"
    r"поголов\w*.{0,35}олен\w*|олен\w*.{0,35}поголов\w*|разведен\w*.{0,30}олен\w*|олен\w*.{0,30}разведен\w*|"
    r"стад\w*.{0,30}олен\w*|олен\w*.{0,30}стад\w*|поддержк\w*.{0,40}оленевод\w*|оленевод\w*.{0,40}поддержк\w*))", re.I)
CONTEXT_SCOPE_RE = re.compile(
    r"(?:якут\w*|саха|красноярск\w*|таймыр\w*|бурят\w*|забайкал\w*|"
    r"иркутск\w*|амурск\w*|хабаровск\w*|сахалин\w*|приморск\w*|томск\w*|тюмен\w*|"
    r"еврейск\w* автономн\w*|еао|арктик\w*|северн\w{0,12}\s+(?:территор\w*|район\w*|народ\w*|посел\w*)|"
    r"хатыстыр\w*|иенгр\w*|иенгринск\w*|олен[её]к\w*|таймыр\w*|росси\w*|российск\w* федерац\w*|\bрф\b)", re.I)
EXCLUDED_TOPIC_RE = re.compile(
    r"(?:\bсво\b|\bsvo\b|специальн\w{0,20}\s+военн\w{0,20}\s+операц\w*"
    r"|\bфронт\w*|\bвоеннослужащ\w*|участник\w*\s+(?:сво|боев\w*)"
    r"|боев\w{0,15}\s+действ\w*|зон\w{0,5}\s+боев\w{0,15}\s+действ\w*"
    r"|путешеств\w*.{0,40}по\s+приамурью.{0,40}бирари\w*)", re.I)
EDITORIAL_RELEVANCE_URLS = {
    "https://news.mail.ru/society/72275373",
    "https://ilken.ru/2026/10/14/v-novosibirske-otkrylas-vserossijskaya-nauchnaya-konferencziya-yazyki-narodov-sibiri-i-sopredelnyh-regionov",
    "https://ilken.ru/2026/10/11/bakaldyn-prazdnik-vstrechi-kotoryj-vernul-menya-v-detstvo",
    "https://ilken.ru/2026/10/11/sahamin-afanasev-i-elena-golomareva-obsudili-itogovyj-dokument-ii-foruma-zhenshhin-severa",
    "https://ilken.ru/2026/10/10/festival-yazykovoj-mir-arktiki-pokazatel-urovnya-znaniya-yazykov-i-kultury-kmns",
}
EDITORIAL_REGION_BY_URL = {
    "https://ilken.ru/2026/10/14/v-novosibirske-otkrylas-vserossijskaya-nauchnaya-konferencziya-yazyki-narodov-sibiri-i-sopredelnyh-regionov": "Якутия",
    "https://ilken.ru/2026/10/11/bakaldyn-prazdnik-vstrechi-kotoryj-vernul-menya-v-detstvo": "Якутия",
    "https://ilken.ru/2026/10/11/sahamin-afanasev-i-elena-golomareva-obsudili-itogovyj-dokument-ii-foruma-zhenshhin-severa": "Якутия",
    "https://ilken.ru/2026/10/10/festival-yazykovoj-mir-arktiki-pokazatel-urovnya-znaniya-yazykov-i-kultury-kmns": "Якутия",
    "https://indigenous-russia.com/archives/50623": "Зарубежные источники",
    "https://t.me/biraria/4225": "Еврейская автономная область",
}
REGION_PATTERNS = {
    "Амурская область": re.compile(r"амурск\w*|благовещенск\w*|бомнак\w*|тынд\w*", re.I),
    "Бурятия": re.compile(r"бурят\w*|улан[- ]?удэ\w*|баунтовск\w*|курумкан\w*|баунт\w*", re.I),
    "Забайкальский край": re.compile(r"забайкал\w*|чит(?:а|е|у|ой)\b|каларск\w*|кыринск\w*", re.I),
    "Еврейская автономная область": re.compile(r"\bеао\b|еврейск\w* автономн\w*|биробиджан\w*|николаевк\w*|теплоозерск\w*|сагды-бир\w*|бирари\w*", re.I),
    "Иркутская область": re.compile(r"иркутск\w*|ербогач[её]н\w*|бодайбинск\w*|качуг\w*|приангар\w*", re.I),
    "Красноярский край": re.compile(r"красноярск\w*|эвенкия|эвенкии|эвенкийск\w*\s+(?:муниципальн\w*\s+)?(?:округ|район)\w*|туру\w*|ванавар\w*|байкит\w*|баикит\w*|нижн\w* тунгуск\w*|ессе\w*|эконд\w*", re.I),
    "Приморский край": re.compile(r"примор\w*|владивосток\w*", re.I),
    "Сахалинская область": re.compile(r"сахалин\w*|южно-сахалинск\w*", re.I),
    "Томская область": re.compile(r"томск\w*|бакчар\w*", re.I),
    "Тюменская область": re.compile(r"тюмен\w*", re.I),
    "Хабаровский край": re.compile(r"хабаровск\w*|комсомольск-на-амуре\w*|ульчск\w*|аяно-майск\w*", re.I),
    "Якутия": re.compile(r"якут\w*|республик\w* саха|\bсаха\b|оймякон\w*|иенгр\w*|хатыстыр\w*|нерюнгри\w*|алдан\w*", re.I),
}
EAST_ASIAN_SCRIPT_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
CHINESE_ADMIN_PLACE_RE = re.compile(r"鄂温克族自治旗|鄂温克自治旗|鄂温克旗|鄂伦春自治旗|鄂伦春旗")
CHINESE_RELEVANCE_CONTEXT_RE = re.compile(r"文化|传统|語言|语言|民俗|民族|生活|经济|經濟|牧业|牧業|狩猎|狩獵|驯鹿|馴鹿|放牧|非遗|非遺|节庆|節慶|手工艺|手工藝|舞蹈|歌曲|历史|歷史|教育")
SOLON_TOKEN_RE = re.compile(r"\bсолон[а-яё]*\b", re.I)
SOLON_CONTEXT_RE = re.compile(r"эвенк|ороч[её]н|хамниган|манегр|тунгус|evenki|ewenki|oroqen|orochon|鄂温克|鄂伦春|народ|этнос|язык|культур|традиц|обыча|истори|наслед|шаман|оленевод|олен|охот|хозяйств|фольклор|поселен|автономн", re.I)
MONGOLIAN_HOMONYM_RE = re.compile(r"(?:\bсолонго\w*|\bсолонгос\w*|\bсолонц\w*|\bsolongo\w*|\bsolongos\w*)", re.I)
EXCLUDED_STORY_URLS = {
    "https://t.me/biraria/4194",
    'https://t.me/EAOMedia/47585',
    'https://t.me/biraria/4207',
    'https://t.me/biraria/4219',
    'https://t.me/biraria/4220',
    'https://t.me/biraria/4221',
    'https://t.me/biraria/4223',
    'https://t.me/biraria/4224',
    'https://t.me/biraria/4234',
    'https://ikon.mn/n/3qs9',
    'https://ikon.mn/n/3qy0',
    'https://t.me/biraria/4218',
    'https://www.ief.ac.cn/dzxx/info/2026/97221.html',
    'https://www.mnb.mn/article/solongo-1-2-tusliin-oron-suutsny-songon-shalgaruulalt-aravdugaar-sardaa-bagtaj-yavagdana-8690',
    'https://ikon.mn/n/3qy0',
    'https://ikon.mn/n/3qs9',
    'https://ngs24.ru/text/gorod/2026/10/12/76694947',
    'https://news.google.com/rss/articles/CBMiV0FVX3lxTFAwZ2FEZk54SFZKb3BRa3NZWkFBWFY0Q3BnY3FJZ19uRThBQ2dLQnRlcC1ZQkFuUFFsWENIcjBXbk9WcjNoX0xhVThKaFhtdEQtbENBRmpIMNIBXEFVX3lxTE50aGZGX2E4YXNQX1pScHNEMGo4WEhGX3NmY2tZenhlaGdoazhUOEVSQUI3VUd0RnMtQW41aUdoSDFydG9nbGFpamlhY21lZlBUMVRNZExoVDNOTW1j?oc=5',
    'https://news.google.com/rss/articles/CBMisAFBVV95cUxOU0E3b0FQU1J0ZXJBUVdDU2tzekx6cWI5Sm1YdFdrSGZpSzNiSC1qb2h3aVQtZDFLN2JXTFJaRS1sVTg1MWxEd2NrakdrTjlPU2pBWGFDcldoTXZpSjJFNmdBX0d0WW5GRFFHenhFcGdsUEJURVpOTUxHT0FObkR2V2ZxaGZnd1ZTRllOd1kwUVRxc1N4bkhveXNDMF9TMXZXMVhsUFROYk01eXBuWWtWbg?oc=5',
}


def story_text(item: dict[str, object]) -> str:
    return " ".join(str(item.get(key, "")) for key in ("title", "description", "desc", "articleText"))


def needs_fulltext_review(item: dict[str, object]) -> bool:
    """Retain borderline candidates for bounded full-article relevance review."""
    return bool(FULLTEXT_CANDIDATE_RE.search(" ".join(
        str(item.get(key, "")) for key in ("title", "description", "desc"))))


def review_fulltext_candidates(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Read ambiguous candidates and every recent Russian-language Ilken article."""
    discovery = json.loads(SOURCES_FILE.read_text(encoding="utf-8")).get("directDiscovery", {})
    max_reviews = max(0, min(100, int(discovery.get("maxFullTextReviews", MAX_FULLTEXT_REVIEWS))))
    workers = max(1, min(12, int(discovery.get("fullTextWorkers", 8))))
    timeout = max(3, min(20, int(discovery.get("fullTextTimeoutSeconds", 10))))
    pending = [
        item for item in items
        if (item.get("needsFullText") == "1" or (
            (urllib.parse.urlsplit(item.get("url", "")).hostname or "").lower() in {"ilken.ru", "www.ilken.ru"}
            and item.get("ilkenEvenki") != "1"
        )) and not is_excluded_story(item)
    ]
    pending.sort(key=lambda item: (
        (urllib.parse.urlsplit(item.get("url", "")).hostname or "").lower() not in {"ilken.ru", "www.ilken.ru"},
        item.get("configuredSource") != "1",
        item.get("source", ""),
    ))
    unique_pending = {}
    for item in pending:
        unique_pending.setdefault(news_sources.canonical_url(item.get("url", "")), item)
    pending = list(unique_pending.values())
    if len(pending) > max_reviews:
        AUDIT.event("fulltext-review", "candidate_limit", omitted=len(pending) - max_reviews)
        pending = pending[:max_reviews]

    def inspect(item: dict[str, str]) -> tuple[dict[str, str], str, str]:
        url = item.get("url", "")
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        targets = [url]
        if host in {"ilken.ru", "www.ilken.ru"}:
            targets.append("https://r.jina.ai/" + url)
        last_error = ""
        for target in targets:
            try:
                payload = request(target, timeout=timeout)
                document = news_sources.decode_html(payload)
                page = news_sources.Page(document, url)
                article_text = clean(page.article_text)
                if len(article_text) < 120 and target.startswith("https://r.jina.ai/"):
                    article_text = clean(re.sub(r"!\[[^]]*\]\([^)]*\)|\[([^]]+)\]\([^)]*\)|^#+\s*", r"\1 ", document, flags=re.M))
                if len(article_text) < 120:
                    last_error = "short_article_text"
                    continue
                checked = {**item, "articleText": article_text}
                if is_excluded_story(checked):
                    return item, "editorial_exclusion_full_text", ""
                relevance = story_relevance(checked)
                if not relevance:
                    return item, "irrelevant_full_text", ""
                item["detectedRelevance"] = relevance
                item["detectedRegion"] = story_region(checked, "Общие новости")
                item["needsFullText"] = "0"
                return item, "full_text_relevant", ""
            except (OSError, ValueError, urllib.error.URLError, TimeoutError) as error:
                last_error = type(error).__name__
        return item, "full_text_failed", last_error

    accepted = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for item, reason, detail in executor.map(inspect, pending):
            AUDIT.event(item.get("source", "fulltext-review"), reason, item.get("url", ""), detail=detail)
            if reason == "full_text_relevant":
                accepted.append(item)
    reviewed_ids = {id(item) for item in pending}
    result = [item for item in items if id(item) not in reviewed_ids]
    result.extend(accepted)
    return result


def is_excluded_story(item: dict[str, object]) -> bool:
    text = story_text(item)
    chinese_place_only = (
        bool(EAST_ASIAN_SCRIPT_RE.search(text))
        and bool(CHINESE_ADMIN_PLACE_RE.search(text))
        and not EVENKI_MENTION_RE.search(CHINESE_ADMIN_PLACE_RE.sub("", text))
        and not CHINESE_RELEVANCE_CONTEXT_RE.search(text)
    )
    story_url = str(item.get("url") or item.get("link") or "").rstrip("/")
    return (
        story_url in EXCLUDED_STORY_URLS
        or "solongo-1-2" in story_url.casefold()
        or bool(EXCLUDED_TOPIC_RE.search(text))
        or (bool(MONGOLIAN_HOMONYM_RE.search(text)) and not EVENKI_MENTION_RE.search(text))
        or (bool(SOLON_TOKEN_RE.search(text)) and not SOLON_CONTEXT_RE.search(text))
        or (bool(re.search(r"камчат[а-яё]*", text, re.I)) and not EVENKI_MENTION_RE.search(text))
        or chinese_place_only
    )


def is_evenki_related(item: dict[str, object]) -> bool:
    return story_relevance(item) is not None


def trusted_category(item: dict[str, object]) -> bool:
    return item.get("ilkenEvenki") == "1" or item.get("arunNews") == "1"


def entity_relevance(text: str) -> bool:
    data = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    for entity in data.get("relevanceEntities", []):
        aliases = entity.get("aliases", [])
        if not any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.I) for alias in aliases):
            continue
        topics = entity.get("topics", [])
        if not topics or any(re.search(term, text, re.I) for term in topics):
            return True
    return False


def story_relevance(item: dict[str, object]) -> str | None:
    url = str(item.get("url", item.get("link", ""))).rstrip("/")
    text = story_text(item)
    if url in EDITORIAL_RELEVANCE_URLS or EVENKI_MENTION_RE.search(text):
        return "direct"
    if item.get("detectedRelevance") in {"direct", "context"}:
        return str(item["detectedRelevance"])
    if entity_relevance(text):
        return "context"
    if CONTEXT_TOPIC_RE.search(text) and CONTEXT_SCOPE_RE.search(text):
        return "context"
    return None


def story_region(item: dict[str, object], default: str) -> str:
    """Return the story's subject region when the source feed did not provide it."""
    url = str(item.get("url", item.get("link", ""))).rstrip("/")
    if url in EDITORIAL_REGION_BY_URL:
        return EDITORIAL_REGION_BY_URL[url]
    assigned_region = str(item.get("region") or item.get("detectedRegion") or "")
    if assigned_region and assigned_region != "Общие новости":
        return assigned_region
    text = story_text(item)
    if EAST_ASIAN_SCRIPT_RE.search(text):
        return "Зарубежные источники"
    # Infer a region only when the headline or excerpt names it explicitly.
    # The outlet's home region is not a safe substitute for story location.
    scores: dict[str, int] = {}
    title = str(item.get("title", ""))
    excerpt = " ".join(str(item.get(key, "")) for key in ("description", "desc", "articleText"))
    for region, pattern in REGION_PATTERNS.items():
        score = (4 if pattern.search(title) else 0) + (2 if pattern.search(excerpt) else 0)
        if score:
            scores[region] = score
    if scores:
        highest = max(scores.values())
        winners = [region for region, score in scores.items() if score == highest]
        if len(winners) == 1:
            return winners[0]
    return assigned_region or default


def story_topic_key(item: dict[str, object]) -> tuple[str, str] | None:
    """Group repetitive northern food/fuel supply stories by subject region."""
    text = story_text(item)
    has_supply_activity = bool(SUPPLY_ACTIVITY_RE.search(text))
    has_supply_goods = bool(SUPPLY_GOODS_RE.search(text))
    has_northern_context = bool(NORTH_SUPPLY_CONTEXT_RE.search(text))
    if not (has_supply_activity and has_supply_goods and has_northern_context):
        return None
    region = story_region(item, str(item.get("region") or "Общие новости"))
    if region in {"", "Общие новости", "Зарубежные источники", "Новости на эвенкийском"}:
        return None
    return region, "северный завоз и снабжение"


def source_key(item: dict[str, object]) -> str:
    source = str(item.get("source", "Источник")).casefold().strip()
    if re.search(r"бирари|biraria", source):
        return "бирария"
    if re.search(r"эвенкийск\w*.{0,12}жизн|newsevenkia", source):
        return "эвенкийская жизнь"
    source = re.sub(r"\s*[·|—–-]\s*(?:telegram|тг|вконтакте|vk)\s*$", "", source)
    return re.sub(r"[^a-zа-яё0-9]+", " ", source).strip() or "источник"


def diversify_items(items: list[dict[str, object]], max_per_source: int | None = None) -> list[dict[str, object]]:
    """Interleave publishers so one prolific outlet does not fill a whole feed."""
    buckets: dict[str, list[dict[str, object]]] = {}
    for item in items:
        buckets.setdefault(source_key(item), []).append(item)
    for bucket in buckets.values():
        bucket.sort(key=lambda item: str(item.get("published", item.get("date", ""))), reverse=True)
    keys = sorted(buckets, key=lambda key: str(buckets[key][0].get("published", buckets[key][0].get("date", ""))), reverse=True)
    result: list[dict[str, object]] = []
    while keys:
        remaining = []
        for key in keys:
            bucket = buckets[key]
            if bucket and (max_per_source is None or sum(source_key(row) == key for row in result) < max_per_source):
                result.append(bucket.pop(0))
            if bucket and (max_per_source is None or sum(source_key(row) == key for row in result) < max_per_source):
                remaining.append(key)
        keys = remaining
    return result


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


def quote_search_term(term: str) -> str:
    """Keep intentional phrase quotes and leave geographic qualifiers outside them."""
    term = str(term).strip()
    return term if '"' in term or any(char.isspace() for char in term) else f'"{term}"'


def load_social_search_sites() -> list[str]:
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    sites = [str(account.get("googleNewsSite", "")).strip() for account in data.get("socialAccounts", [])]
    return [site for site in sites if re.fullmatch(r"[a-z0-9.-]+/[a-zA-Z0-9_./-]+", site)]


def load_source_domains() -> list[str]:
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    domains = [str(value).strip().lower() for value in data.get("domains", [])]
    for country in data.get("internationalMedia", []):
        domains.extend(
            str(publisher.get("domain", "")).strip().lower()
            for publisher in country.get("publishers", [])
        )
    domains = list(dict.fromkeys(domains))
    domains = [value for value in domains if re.fullmatch(r"[a-z0-9.-]+|[^\s/]+", value)]
    if not domains:
        raise ValueError("No source domains found in news-search-sources.json")
    return domains


def request(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 25) -> bytes:
    parts = urllib.parse.urlsplit(url)
    if parts.hostname:
        ascii_host = parts.hostname.encode("idna").decode("ascii")
        url = urllib.parse.urlunsplit((parts.scheme, parts.netloc.replace(parts.hostname, ascii_host),
            urllib.parse.quote(parts.path, safe="/%:@"), urllib.parse.quote(parts.query, safe="%=&?/:;+,@"), ""))
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "TaezhnayaNit-NewsMonitor/1.0 (RSS reader)"} | (headers or {}),
    )
    host = urllib.parse.urlsplit(url).hostname or "unknown"
    # Do not log API credentials, token-bearing paths, or request bodies.
    safe_url = url if host not in {"api.telegram.org", "api.vk.com"} else "https://" + host
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read(4_000_001)
            if len(payload) > 4_000_000:
                raise ValueError("response_size_limit")
        AUDIT.event(host, "http_ok", safe_url)
        return payload
    except (OSError, ValueError) as error:
        AUDIT.event(host, "http_failed", safe_url, error=type(error).__name__, httpStatus=getattr(error, "code", None))
        raise


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
            russian = parse_russian_publication_date(value)
            if russian:
                return russian
            match = re.fullmatch(r"(\d{2})[./](\d{2})[./](\d{4})(?:\s+(\d{2}):(\d{2}))?", value.strip())
            if match:
                day, month, year, hour, minute = match.groups()
                try:
                    return dt.datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), tzinfo=TZ)
                except ValueError:
                    pass
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
    AUDIT.event("google-redirect", "unresolved_redirect", url)
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
            AUDIT.event("arun-news", "outside_window_or_future", str(story["url"]))
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
                valid_link = (
                    link.startswith("https://ilken.ru/evenki/")
                    if is_evenki_feed
                    else link.startswith("https://ilken.ru/") and "/evenki/" not in link
                )
                reason = ("missing_title" if not title else "invalid_url" if not valid_link else "invalid_date" if not published else
                          "outside_window" if published < feed_cutoff else "future_date" if published > now_local() + dt.timedelta(hours=6) else None)
                if reason:
                    AUDIT.event(str(feed["id"]), reason, link)
                    continue
                guid = clean(node.findtext("guid", ""))
                found.append({
                    "id": guid or link, "title": title, "source": "Илкэн · Улгур",
                    "url": link, "published": published.isoformat(timespec="minutes"),
                    "day": published.date().isoformat(), "description": description,
                    "ilkenEvenki": "1" if is_evenki_feed else "0",
                    "configuredSource": "0" if is_evenki_feed else "1",
                    "needsFullText": "1" if not is_evenki_feed else "0",
                })
        except (OSError, ValueError, ET.ParseError, KeyError) as error:
            AUDIT.event(str(feed["id"]), "rss_failed", str(feed["url"]), error=type(error).__name__)
            print(f"Warning: direct RSS failed for {feed.get('label', 'source')}: {error}", file=sys.stderr)

        # The publisher's RSS is currently returning HTTP 555 to GitHub Actions.
        # The category HTML is public and includes each story's date in its permalink.
        if feed.get("category"):
            try:
                page = request(str(feed["category"]), headers={
                    "User-Agent": "Mozilla/5.0 (compatible; TaezhnayaNit-NewsMonitor/1.0)",
                    "Accept": "text/html,application/xhtml+xml",
                }).decode("utf-8", errors="replace")
                category_stories = IlkenCategoryParser().parse(page)
                for story in category_stories:
                    published = story["published"]
                    reason = "outside_window" if published < feed_cutoff else "future_date" if published > now_local() + dt.timedelta(hours=6) else None
                    if reason:
                        AUDIT.event(str(feed["id"]), reason, str(story["url"]))
                        continue
                    item = {"title": story["title"], "description": story["description"], "url": story["url"]}
                    found.append({
                        "id": story["url"], "title": story["title"], "source": "Илкэн · Улгур",
                        "url": story["url"], "published": published.isoformat(timespec="minutes"),
                        "day": published.date().isoformat(),
                        "description": story["description"],
                        "needsFullText": "1" if not is_evenki_feed else "0",
                        "ilkenEvenki": "1" if is_evenki_feed else "0",
                        "configuredSource": "0" if is_evenki_feed else "1",
                    })
                count = len(found) - feed_start
                if count:
                    print(f"Read {count} recent stories from the Ilken category page.")
            except (OSError, urllib.error.URLError, TimeoutError, KeyError, ValueError) as error:
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
                reader_stories = parse_ilken_reader_markdown(markdown)
                for story in reader_stories:
                    published = story["published"]
                    reason = "outside_window" if published < feed_cutoff else "future_date" if published > now_local() + dt.timedelta(hours=6) else None
                    if reason:
                        AUDIT.event(str(feed["id"]), reason, str(story["url"]))
                        continue
                    item = {"title": story["title"], "description": story["description"], "url": story["url"]}
                    found.append({
                        "id": story["url"], "title": story["title"], "source": "Илкэн · Улгур",
                        "url": story["url"], "published": published.isoformat(timespec="minutes"),
                        "day": published.date().isoformat(),
                        "description": story["description"],
                        "needsFullText": "1" if not is_evenki_feed else "0",
                        "ilkenEvenki": "1" if is_evenki_feed else "0",
                        "configuredSource": "0" if is_evenki_feed else "1",
                    })
                count = len(found) - feed_start
                if count:
                    print(f"Read {count} recent stories from the Ilken category via Reader fallback.")
                else:
                    print("Warning: Reader fallback returned no recent Ilken category stories.", file=sys.stderr)
            except (OSError, KeyError, ValueError) as error:
                print(f"Warning: Ilken Reader fallback failed: {error}", file=sys.stderr)
    return found


class IlkenCategoryParser(HTMLParser):
    """Extract dated article links and nearby excerpts from Ilken archives."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, object]] = []
        self._card: dict[str, object] | None = None
        self._anchor_depth = 0
        self._description_depth = 0
        self._description_done = False

    def parse(self, document: str) -> list[dict[str, object]]:
        self.feed(document)
        self._finish_card()
        unique: dict[str, dict[str, object]] = {}
        for card in self.cards:
            url = str(card.get("url", ""))
            if not ilken_permalink_date(url):
                continue
            entry = unique.setdefault(url, {"url": url, "title": "", "description": ""})
            for key in ("title", "description"):
                value = clean(str(card.get(key, "")))
                if value and (key == "title" or not entry.get(key)):
                    entry[key] = value
        return [
            {**card, "published": ilken_permalink_date(str(card["url"]))}
            for card in unique.values()
            if card.get("title") and ilken_permalink_date(str(card["url"])) is not None
        ]

    def _finish_card(self) -> None:
        if self._card is not None:
            self.cards.append(self._card)
            self._card = None
        self._anchor_depth = 0
        self._description_depth = 0
        self._description_done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a":
            href = attributes.get("href") or ""
            if ilken_permalink_date(href):
                self._finish_card()
                self._card = {"url": href, "title": "", "description": ""}
                self._anchor_depth = 1
                return
            if self._anchor_depth:
                self._anchor_depth += 1
        elif self._card is not None and not self._anchor_depth and not self._description_done and tag == "p":
            self._description_depth = 1
        elif self._description_depth and tag == "p":
            self._description_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor_depth:
            self._anchor_depth -= 1
        elif tag == "p" and self._description_depth:
            self._description_depth -= 1
            if not self._description_depth:
                self._description_done = True

    def handle_data(self, data: str) -> None:
        if self._card is None:
            return
        if self._anchor_depth:
            self._card["title"] = str(self._card["title"]) + data
        elif self._description_depth:
            self._card["description"] = str(self._card["description"]) + data


def ilken_permalink_date(url: str) -> dt.datetime | None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname not in {"ilken.ru", "www.ilken.ru"}:
        return None
    match = re.search(r"/(?:evenki/)?(\d{4})/(\d{2})/(\d{2})/", parsed.path)
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
        r'(?P<url>https://ilken\.ru/(?:evenki/)?\d{4}/\d{2}/\d{2}/[^\s)]+)'
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
                if self.capture_text:
                    self.text_div_depth += 1
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
        posts = []
        before = None
        page_limit = 8
        reached_cutoff = False
        visited_pages = set()
        for page_index in range(page_limit):
            preview_url = f"https://t.me/s/{username}" + (f"?before={before}" if before else "")
            try:
                page = request(preview_url, headers={"Accept": "text/html"}, timeout=15).decode("utf-8", errors="replace")
            except (OSError, ValueError) as error:
                AUDIT.event(str(account["id"]), "request_failed", preview_url, error=type(error).__name__)
                break
            parser = TelegramPublicChannelParser()
            parser.feed(page)
            if not parser.posts:
                AUDIT.event(str(account["id"]), "empty_or_unavailable_preview", preview_url)
                break
            ids = [int(post["post"].rsplit("/", 1)[-1]) for post in parser.posts if re.search(r"/\d+$", post.get("post", ""))]
            posts.extend(parser.posts)
            dates = [parse_date(post.get("date", "")) for post in parser.posts]
            if any(date and date < cutoff for date in dates):
                reached_cutoff = True
                break
            if not ids or min(ids) in visited_pages:
                AUDIT.event(str(account["id"]), "pagination_stalled", preview_url)
                break
            before = min(ids)
            visited_pages.add(before)
        else:
            AUDIT.event(str(account["id"]), "telegram_page_limit", pages=page_limit)
        AUDIT.event(str(account["id"]), "preview_parsed", returned=len(posts), reachedCutoff=reached_cutoff)
        for post in posts:
            published = parse_date(post.get("date", ""))
            text = clean(post.get("text", ""))
            reason = ("invalid_date" if not published else "outside_window" if published < cutoff else
                      "future_date" if published > now_local() + dt.timedelta(hours=6) else
                      "editorial_exclusion" if is_excluded_story({"description": text}) else
                      "irrelevant" if not is_evenki_related({"description": text}) else "accepted")
            AUDIT.event(str(account["id"]), reason, post.get("url", ""))
            if reason != "accepted":
                continue
            post_path = post.get("post", "").strip("/")
            post_url = f"https://t.me/{post_path}" if post_path else post.get("url", "")
            if not post_url.startswith("https://t.me/"):
                continue
            # Keep source posts readable when we reuse them on the site and in
            # the channel: Telegram decorations should not become part of the
            # headline or summary.
            display_text = telegram_text(text)
            found.append({
                "id": post_url,
                "title": display_text[:180].rstrip(" .…") or str(account.get("label", "Telegram")),
                "source": str(account.get("label", "Telegram")),
                "url": post_url,
                "published": published.isoformat(timespec="minutes"),
                "day": published.date().isoformat(),
                "description": display_text[:420],
                "socialPlatform": "Telegram",
                "detectedRelevance": story_relevance({"description": text}) or "",
                "configuredSource": "1",
                **({"image": post["image"]} if post.get("image") else {}),
            })
    print(f"Read {len(found)} recent relevant posts directly from public Telegram channels.")
    return found


def fetch_vk_public_walls() -> list[dict[str, str]]:
    """Read configured public VK walls through the official API when configured."""
    token = os.environ.get("VK_ACCESS_TOKEN", "").strip()
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    cutoff = now_local() - dt.timedelta(hours=LOOKBACK_HOURS)
    found = []
    for account in data.get("socialAccounts", []):
        parsed = urllib.parse.urlsplit(str(account.get("url", "")))
        if parsed.hostname not in {"vk.com", "vk.ru", "www.vk.com", "www.vk.ru"}:
            continue
        source = str(account["id"])
        if not token:
            AUDIT.event(source, "missing_vk_token", str(account.get("url", "")))
            continue
        domain = parsed.path.strip("/").split("/")[0]
        posts = []
        for offset in range(0, 800, 100):
            params = {"count": 100, "offset": offset, "filter": "owner", "access_token": token, "v": "5.199"}
            numeric = re.fullmatch(r"(?:public|club)(\d+)", domain)
            params["owner_id" if numeric else "domain"] = -int(numeric.group(1)) if numeric else domain
            try:
                result = json.loads(request("https://api.vk.com/method/wall.get", data=urllib.parse.urlencode(params).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15))
                if result.get("error"):
                    AUDIT.event(source, "vk_api_error", errorCode=result["error"].get("error_code"))
                    break
                batch = result.get("response", {}).get("items", [])
            except (OSError, ValueError, AttributeError):
                AUDIT.event(source, "vk_request_failed")
                break
            posts.extend(batch)
            # A pinned old post must not stop pagination through newer posts.
            dates = [int(post.get("date", 0)) for post in batch if not post.get("is_pinned")]
            if len(batch) < 100 or (dates and max(dates) < cutoff.timestamp()):
                break
            time.sleep(0.35)
        else:
            AUDIT.event(source, "vk_page_limit", pages=8)
        AUDIT.event(source, "wall_parsed", returned=len(posts))
        for post in posts:
            text = clean(str(post.get("text", "")))
            # Include the public repost's text when the wall wrapper is empty.
            text = clean(text + " " + " ".join(str(copy.get("text", "")) for copy in post.get("copy_history", [])))
            try:
                published = dt.datetime.fromtimestamp(int(post.get("date", 0)), tz=TZ)
                post_url = f"https://vk.com/wall{int(post['owner_id'])}_{int(post['id'])}"
            except (ValueError, TypeError, KeyError, OverflowError, OSError):
                AUDIT.event(source, "invalid_post")
                continue
            reason = ("outside_window" if published < cutoff else "future_date" if published > now_local() + dt.timedelta(hours=6)
                      else "editorial_exclusion" if is_excluded_story({"description": text}) else
                      "irrelevant" if not is_evenki_related({"description": text}) else "accepted")
            AUDIT.event(source, reason, post_url)
            if reason != "accepted":
                continue
            found.append({"id": post_url, "title": text[:180].rstrip(" .…") or str(account.get("label", "ВКонтакте")),
                "source": str(account.get("label", "ВКонтакте")), "url": post_url,
                "published": published.isoformat(timespec="minutes"), "day": published.date().isoformat(),
                "description": text[:420], "detectedRelevance": story_relevance({"description": text}) or "", "socialPlatform": "ВКонтакте", "configuredSource": "1"})
    return found


def fetch_items() -> list[dict[str, str]]:
    domains = load_source_domains()
    manifest = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    for account in manifest.get("socialAccounts", []) + manifest.get("directFeeds", []):
        AUDIT.event(str(account["id"]), "configured", str(account.get("url") or account.get("category", "")))

    # Search the full Google News index one phrase at a time. Google News RSS
    # inconsistently handles long OR expressions, which can silently return an
    # empty feed. Individual queries also make it possible to see which terms
    # actually discover stories.
    feeds: list[tuple[str, bool, dict[str, str] | None]] = []
    for group_id in ("core", "language-education", "culture", "historical-and-local-names", "regional-context", "local-entities", "map-localities"):
        terms = load_query_group(group_id)
        feeds.extend((f"{quote_search_term(term)} when:7d", False, None) for term in terms)
    international_terms = load_query_group("international-ethnonyms")
    feeds.extend(
        (f"{quote_search_term(term)} when:7d", False, {"hl": "en-US", "gl": "US", "ceid": "US:en"})
        for term in international_terms
    )

    # Search every configured publisher separately. Combining many sites into
    # one Google News query can crowd out smaller outlets in the RSS results.
    source_terms = (
        "эвенки", "эвенк", "эвенкийский", "эвенкия", "эвенкил", "эвэды",
        "орочон", "орочёны", "хамниган", "тунгус", "бирар", "манегр",
        "солоны эвенки", "бакалдын", "мучун", "оленеводство", "оленеводы",
        "поголовье оленей", "пастбища оленеводов", "разведение оленей",
        "экспорт северных оленей", "экспорт оленей Китай", "Гэньхэ оленеводство",
        "Тянский эвенкийский наслег", "побратимские связи Гэньхэ",
        "Хатыстыр", "северный завоз", "оленеводческие хозяйства Арктики",
    )
    source_query = " OR ".join(quote_search_term(term) for term in (*source_terms, *load_query_group("local-entities")))
    # Search Asian outlets with the ethnonyms used in their publication languages.
    # Keep each publisher separate so one large source cannot crowd out smaller ones.
    sources_data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    international_domains = {
        str(publisher.get("domain", "")).strip().lower()
        for country in sources_data.get("internationalMedia", [])
        for publisher in country.get("publishers", [])
    }
    feeds.extend(
        (f"site:{domain} ({source_query}) when:2d", False, None)
        for domain in domains
        if domain not in international_domains
    )
    for country in sources_data.get("internationalMedia", []):
        terms = [str(term).strip() for term in country.get("queries", []) if str(term).strip()]
        if not terms:
            continue
        localized_query = " OR ".join(f'"{term}"' for term in terms)
        locale = country.get("googleNews")
        if not isinstance(locale, dict):
            locale = None
        for publisher in country.get("publishers", []):
            domain = str(publisher.get("domain", "")).strip().lower()
            if domain:
                feeds.append((f"site:{domain} ({localized_query}) when:7d", False, locale))

    # Search non-Russian ethnonyms individually in their native editions. These
    # are easy to lose inside broad site-restricted queries and often appear in
    # local reporting that is not indexed by the Russian edition.
    for country in sources_data.get("internationalMedia", []):
        locale = country.get("googleNews")
        terms = [str(term).strip() for term in country.get("queries", []) if str(term).strip()]
        if isinstance(locale, dict):
            feeds.extend((f"{quote_search_term(term)} when:7d", False, locale) for term in terms)

    local_terms = load_query_group("eao-evenki")
    if local_terms:
        local_query = " OR ".join(quote_search_term(term) for term in local_terms)
        feeds.append((f"({local_query}) when:30d", False, None))

    # Search every configured public social account across all major topic groups,
    # not only the regional EAO terms. Google News provides public index coverage;
    # direct access to private posts or unindexed content requires platform APIs.
    social_sites = load_social_search_sites()
    for group_id in ("core", "language-education", "culture", "historical-and-local-names", "regional-context", "eao-evenki", "local-entities"):
        terms = load_query_group(group_id)
        if not terms:
            continue
        social_query = " OR ".join(quote_search_term(term) for term in terms)
        feeds.extend((f"site:{site} ({social_query}) when:7d", False, None) for site in social_sites)
    ilken_terms = load_ilken_queries()
    # Search both Ilken's Evenki-language section and its Russian-language articles.
    # The Russian feed is relevance-filtered from the article text/teaser below.
    feeds.append(("site:ilken.ru/evenki/ when:30d", True, None))
    feeds.extend((f'site:ilken.ru/evenki/ "{term}" when:30d', True, None) for term in ilken_terms)
    feeds.append(("site:ilken.ru (эвенки OR эвенкийский OR Бакалдын OR орочоны OR хамниганы) when:7d", False, None))

    # Search each configured East Asian language edition across the regional index,
    # in addition to searching each named publisher separately.
    for country in sources_data.get("internationalMedia", []):
        terms = [str(term).strip() for term in country.get("queries", []) if str(term).strip()]
        locale = country.get("googleNews")
        if terms and isinstance(locale, dict):
            localized_query = " OR ".join(f'"{term}"' for term in terms)
            feeds.append((f"({localized_query}) when:7d", False, locale))

    cutoff = now_local() - dt.timedelta(hours=LOOKBACK_HOURS)

    def search_feed(feed: tuple[str, bool, dict[str, str] | None]) -> tuple[list[dict[str, str]], str | None, tuple[int, int, int, int]]:
        feed_query, ilken_search, locale = feed
        params = urllib.parse.urlencode({"q": feed_query, **(locale or {"hl": "ru", "gl": "RU", "ceid": "RU:ru"})})
        try:
            payload = request(f"{RSS_URL}?{params}", timeout=12)
            root = ET.fromstring(payload)
        except (OSError, ValueError, ET.ParseError) as error:
            AUDIT.event(feed_query, "search_failed", error=type(error).__name__)
            return [], str(error), (0, 0, 0, 0)

        found: list[dict[str, str]] = []
        nodes = root.findall("./channel/item")
        recent_count = link_count = relevant_count = 0
        for node in nodes:
            title = clean(node.findtext("title", ""))
            description = clean(node.findtext("description", ""))
            published = parse_date(node.findtext("pubDate", ""))
            if not published or published < cutoff or published > now_local() + dt.timedelta(hours=6):
                AUDIT.event(feed_query, "invalid_date" if not published else "outside_window" if published < cutoff else "future_date", node.findtext("link", ""))
                continue
            recent_count += 1
            link = clean(node.findtext("link", ""))
            if not link.startswith("https://"):
                continue
            link_count += 1
            source_node = node.find("source")
            source = clean(source_node.text if source_node is not None else "")
            source_host = ""
            if source_node is not None:
                source_host = (urllib.parse.urlsplit(source_node.attrib.get("url", "")).hostname or "").lower()
            guid = clean(node.findtext("guid", ""))
            item_id = guid or link
            is_ilken = ilken_search and "ilken.ru" in (source_host, (urllib.parse.urlsplit(link).hostname or "").lower())
            text_candidate = {"title": title, "description": description}
            relevant = is_evenki_related(text_candidate)
            needs_review = needs_fulltext_review(text_candidate)
            if not relevant and not is_ilken and not needs_review:
                AUDIT.event(feed_query, "irrelevant", link)
                continue
            relevant_count += int(relevant)
            # Resolve Google News redirects only after relevance filtering. This
            # avoids making an extra network request for every irrelevant hit.
            publisher_url = original_source_url(link)
            publisher_host = (urllib.parse.urlsplit(publisher_url).hostname or "").lower()
            configured_source = any(
                host == domain or host.endswith("." + domain)
                for host in (source_host, publisher_host)
                for domain in domains
            ) and "news.google.com" not in publisher_host
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
                "needsFullText": "1" if needs_review and not relevant and not is_ilken else "0",
            })
        AUDIT.event(feed_query, "search_ok", accepted=len(found), returned=len(nodes))
        if len(nodes) >= 100:
            AUDIT.event(feed_query, "possible_search_result_limit")
        return found, None, (len(nodes), recent_count, link_count, relevant_count)

    items: list[dict[str, str]] = []
    failures = 0
    raw_results = recent_results = https_results = relevant_results = 0
    # Keep the run short while spreading requests so no source group monopolizes
    # the limited number of results returned by Google News RSS.
    with ThreadPoolExecutor(max_workers=10) as executor:
        for found, error, metrics in executor.map(search_feed, feeds):
            if error:
                failures += 1
                print(f"Warning: one RSS search failed: {error}", file=sys.stderr)
            items.extend(found)
            raw_results += metrics[0]
            recent_results += metrics[1]
            https_results += metrics[2]
            relevant_results += metrics[3]

    AUDIT.save(AUDIT_FILE, now_local().isoformat(timespec="seconds"))
    direct_items = news_sources.fetch_domains(sys.modules[__name__], domains, sources_data, AUDIT)
    AUDIT.save(AUDIT_FILE, now_local().isoformat(timespec="seconds"))
    for adapter in (fetch_ilken_feed, fetch_arun_news, fetch_telegram_public_channels, fetch_vk_public_walls):
        adapter_items = adapter()
        for item in adapter_items:
            AUDIT.event(item["source"], "adapter_accepted", item["url"])
        direct_items.extend(adapter_items)
    if failures == len(feeds) and not direct_items and not any(AUDIT.rows.get(domain, {}).get("counts", {}).get("request_ok") for domain in domains):
        raise RuntimeError("All Google News RSS searches failed")
    # Deduplicate repeated articles returned by the global and publisher-specific searches.
    candidates = review_fulltext_candidates(items + direct_items)
    excluded = [item for item in candidates if is_excluded_story(item) or (not is_evenki_related(item) and not trusted_category(item))]
    print(
        f"Search complete: {len(feeds)} Google News RSS searches, "
        f"{raw_results} raw results, {recent_results} recent, {https_results} with links, "
        f"{relevant_results} text-relevant, {len(items)} indexed candidates, "
        f"{len(direct_items)} direct-source candidates, "
        f"{len(excluded)} excluded by relevance/editorial filters."
    )
    if excluded:
        print(f"Excluded {len(excluded)} stories by relevance and editorial filters.")
    unique = {}
    for item in candidates:
        source = item.get("auditSource", item.get("source", "unknown"))
        key = news_sources.canonical_url(item["url"])
        if item in excluded:
            AUDIT.event(source, "editorial_exclusion" if is_excluded_story(item) else "irrelevant", item["url"])
        elif key in unique:
            AUDIT.event(source, "duplicate_url", item["url"])
            if trusted_category(item) or item.get("configuredSource") == "1":
                unique[key] = item
        else:
            unique[key] = item
            AUDIT.event(source, "collected", item["url"])
    return diversify_items(list(unique.values()))


def update_site_news_feed(items: list[dict[str, str]]) -> int:
    """Append matching results from configured media and Ilken's Evenki posts."""
    candidates = [item for item in items if item.get("siteEligible") == "1"]
    path = ROOT / "news-data.js"
    stories = load_site_news_stories()
    original_stories = list(stories)
    stories = [story for story in stories if not is_excluded_story(story)]
    known = {news_sources.canonical_url(str(story.get("link", ""))) for story in stories}
    topic_cutoff = now_local() - dt.timedelta(days=TOPIC_STORY_LOOKBACK_DAYS)
    topic_counts: dict[tuple[str, str], int] = {}
    for story in stories:
        published = parse_date(str(story.get("date", "")))
        topic_key = story_topic_key(story)
        if published and published >= topic_cutoff and topic_key:
            topic_counts[topic_key] = topic_counts.get(topic_key, 0) + 1
    added = 0
    for item in candidates:
        if is_excluded_story(item) or (not is_evenki_related(item) and not trusted_category(item)):
            continue
        link = news_sources.canonical_url(item["url"])
        if link in known:
            AUDIT.event(item["source"], "already_on_site", item["url"])
            continue
        topic_key = story_topic_key(item)
        if topic_key and topic_counts.get(topic_key, 0) >= MAX_TOPIC_STORIES_PER_REGION:
            AUDIT.event(
                item["source"], "topic_region_limit", item["url"],
                topic=topic_key[1], region=topic_key[0],
                limit=MAX_TOPIC_STORIES_PER_REGION,
            )
            continue
        relevance = story_relevance(item)
        category = "Новости на эвенкийском" if item.get("ilkenEvenki") == "1" else "Общие новости"
        stories.append({
            "region": story_region(item, category),
            "date": item["day"], "source": item["source"],
            "title": item["title"],
            "desc": (item.get("description") or ("Региональная тема, важная для жизни северных территорий. Читайте оригинал в СМИ." if relevance == "context" else "Публикация о жизни, языке или культуре эвенков. Читайте оригинал в СМИ."))[:420],
            "tags": "северные регионы снабжение охота рыболовство" if relevance == "context" else "эвенки эвенкийский язык новости",
            "relevance": relevance or "direct", "link": item["url"],
            **({"image": item["image"]} if item.get("image") else {}),
        })
        known.add(link)
        if topic_key:
            topic_counts[topic_key] = topic_counts.get(topic_key, 0) + 1
        AUDIT.event(item["source"], "site_added", item["url"])
        added += 1
    stories = diversify_items(stories)
    if added or stories != original_stories:
        stories.sort(key=lambda story: str(story.get("date", "")), reverse=True)
        stories = diversify_items(stories)
        path.write_text("window.newsStories=" + json.dumps(stories, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    return added


def load_site_news_stories() -> list[dict[str, object]]:
    text = (ROOT / "news-data.js").read_text(encoding="utf-8")
    try:
        return json.loads(text[text.find("["):text.rfind("]") + 1])
    except json.JSONDecodeError:
        pass
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
        state = {"version": 1, "seen": {}, "daily": {}, "pendingTelegram": []}
    else:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("Unsupported Telegram news state format")
    state.setdefault("seen", {})
    state.setdefault("daily", {})
    state.setdefault("pendingTelegram", [])
    state.setdefault("deliveredUrls", {})
    for key, value in state["seen"].items():
        if key.startswith(("https://", "http://")) and "news.google.com" not in key:
            state["deliveredUrls"].setdefault(news_sources.canonical_url(key), value)
    for items in state["daily"].values():
        for item in items:
            if item.get("url"):
                state["deliveredUrls"].setdefault(news_sources.canonical_url(item["url"]), item.get("published", ""))
    state["pendingTelegram"] = [item for item in state["pendingTelegram"] if not is_excluded_story(item) and (is_evenki_related(item) or trusted_category(item))]
    state["daily"] = {day: [item for item in items if not is_excluded_story(item) and (is_evenki_related(item) or trusted_category(item))] for day, items in state["daily"].items()}
    return state


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def telegram_send(text: str, *, parse_mode: str | None = "HTML", disable_web_page_preview: bool = True) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "@taiga_thread").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured in GitHub Actions secrets")
    url = f"{BOT_API}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": disable_web_page_preview}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        result = json.loads(request(url, data=body, headers={"Content-Type": "application/json"}))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram sendMessage failed: HTTP {error.code}: {details}") from error
    if not result.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {result.get('description', 'unknown error')}")


EMOJI_RE = re.compile(
    "[\U0001F1E0-\U0001FAFF\U00002600-\U000027BF\uFE0F\u200D\u20E3]+"
)


def telegram_text(value: str) -> str:
    """Remove pictographic emoji from Telegram copy and tidy resulting spaces."""
    return re.sub(r"\s+", " ", EMOJI_RE.sub("", clean(value))).strip()


def plain_item(item: dict[str, str]) -> str:
    parts = [telegram_text(item.get("title", ""))]
    description = telegram_text(item.get("description", ""))
    if description:
        parts.append(description[:900])
    source = telegram_text(item.get("source", "Источник")) or "Источник"
    parts.append(f"{source} · {item.get('published', '')[:10]}\n{item.get('url', '')}")
    return "\n\n".join(parts)



class ArticleImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        marker = (values.get("property") or values.get("name") or "").lower()
        if marker in {"og:image", "og:image:secure_url", "twitter:image", "twitter:image:src"}:
            image = values.get("content", "").strip()
            if image:
                self.images.append(image)


def fetch_article_image(url: str) -> str:
    try:
        page = request(url, headers={"Accept": "text/html,application/xhtml+xml"}, timeout=12).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return ""
    parser = ArticleImageParser()
    parser.feed(page[:500_000])
    for candidate in parser.images:
        image = urllib.parse.urljoin(url, html.unescape(candidate))
        if urllib.parse.urlsplit(image).scheme == "https":
            return image
    return ""

def telegram_send_item(item: dict[str, str]) -> None:
    """Send article imagery to Telegram; website cards remain text-only."""
    if is_excluded_story(item):
        raise RuntimeError("Editorial exclusion blocked a war/SVO story from Telegram")
    image = item.get("image", "").strip() or fetch_article_image(item.get("url", ""))
    if not image:
        try:
            telegram_send(format_item(item), disable_web_page_preview=False)
        except RuntimeError as error:
            print(f"HTML message failed; retrying as plain text: {error}", file=sys.stderr)
            telegram_send(plain_item(item), parse_mode=None, disable_web_page_preview=False)
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
    try:
        result = json.loads(request(url, data=body, headers={"Content-Type": "application/json"}))
        if result.get("ok"):
            return
        detail = result.get("description", "unknown error")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
    print(f"Telegram could not attach image for {item.get('url')}: {detail}; sending plain text instead.", file=sys.stderr)
    telegram_send(plain_item(item), parse_mode=None)


def format_item(item: dict[str, str], number: int | None = None) -> str:
    prefix = f"{number}. " if number is not None else "📰 "
    title = html.escape(telegram_text(item.get("title", "")))
    url = html.escape(item.get("url", ""), quote=True)
    description = telegram_text(item.get("description", ""))
    # Keep title and summary as plain text; link only the source name.
    if len(description) > 420:
        description = description[:417].rsplit(" ", 1)[0] + "…"
    lines = [f"{prefix}{title}"]
    if description:
        lines.append(html.escape(description))
    source = telegram_text(item.get("source", "Источник")) or "Источник"
    lines.append(f"<a href=\"{url}\">{html.escape(source)}</a> · {html.escape(item['published'][:10])}")
    return "\n".join(lines)


def send_digest(today: str, state: dict) -> None:
    items = state["daily"].get(today, [])
    if not items:
        print(f"No matching stories for {today}; digest skipped.")
        return
    selected = items[:MAX_DIGEST_ITEMS]
    parts = [f"Что произошло сегодня — {today}"]
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
    parser.add_argument("--audit-only", action="store_true", help="Collect and write diagnostics without changing site, state or Telegram")
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
            state.setdefault("deliveredUrls", {})[news_sources.canonical_url(item["url"])] = now_local().isoformat(timespec="minutes")
            state["daily"].setdefault(item["day"], []).append(item)
            state["pendingTelegram"].remove(item)
            save_state(state)
            sent += 1
        print(f"Posted {sent} site-published stories to Telegram.")
        return 0

    if args.mode == "digest":
        send_digest(today, state)
        return 0

    try:
        found = fetch_items()
    finally:
        AUDIT.save(AUDIT_FILE, now_local().isoformat(timespec="seconds"))
    if args.audit_only:
        print(f"Audit only: {len(found)} accepted stories; report: {AUDIT_FILE}")
        return 0
    # Search results from configured publishers are added to the general feed;
    # Ilken's dedicated Evenki-language category is a trusted direct-source feed.
    for item in found:
        relevance = story_relevance(item)
        item["relevance"] = relevance or ""
        item["siteEligible"] = "1" if item.get("ilkenEvenki") == "1" or item.get("arunNews") == "1" or item.get("configuredSource") == "1" or relevance else "0"
    new_site_stories = update_site_news_feed(found) if args.mode == "collect" else 0
    if new_site_stories:
        print(f"Added {new_site_stories} new stories to the website news feed.")
    # Expire IDs older than a month and old digest buckets.
    expiry = now_local() - dt.timedelta(days=MAX_SEEN_DAYS)
    state["seen"] = {
        key: value for key, value in state["seen"].items()
        if (parse_date(value) or now_local()) >= expiry
    }
    state["deliveredUrls"] = {url: value for url, value in state.get("deliveredUrls", {}).items()
                              if (parse_date(value) or now_local()) >= expiry}
    state["daily"] = {day: items for day, items in state["daily"].items() if day >= (now_local().date() - dt.timedelta(days=7)).isoformat()}

    public_links = {str(story.get("link", "")).rstrip("/") for story in load_site_news_stories()}
    telegram_cutoff = now_local() - dt.timedelta(hours=LOOKBACK_HOURS)
    state["pendingTelegram"] = [
        item for item in state["pendingTelegram"]
        if (parse_date(item.get("published", "")) or now_local()) >= telegram_cutoff
    ]
    queued_ids = {item.get("id") for item in state["pendingTelegram"]}
    queued_candidates = [
        item for item in found
        if item.get("siteEligible") == "1"
        and not is_excluded_story(item)
        and (is_evenki_related(item) or trusted_category(item))
        and (parse_date(item.get("published", "")) or now_local()) >= telegram_cutoff
        and item["url"].rstrip("/") in public_links
        and item["id"] not in state["seen"]
        and item["id"] not in queued_ids
    ]
    # Remove delivered URLs before applying the notification quota.
    known_delivery_urls = {news_sources.canonical_url(item["url"]) for item in state["pendingTelegram"]}
    known_delivery_urls.update(state.get("deliveredUrls", {}))
    candidates_to_queue = []
    for item in queued_candidates:
        if news_sources.canonical_url(item["url"]) in known_delivery_urls:
            AUDIT.event(item["source"], "telegram_already_delivered_or_pending", item["url"])
        else:
            candidates_to_queue.append(item)
    queued = diversify_items(candidates_to_queue, max_per_source=4)
    for item in candidates_to_queue:
        AUDIT.event(item["source"], "telegram_queued" if item in queued else "telegram_source_limit", item["url"])
    state["pendingTelegram"].extend(queued)
    print(f"Fetched {len(found)} candidates; added {new_site_stories} to the site and queued {len(queued)} for Telegram after publication.")

    save_state(state)
    AUDIT.save(AUDIT_FILE, now_local().isoformat(timespec="seconds"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, ET.ParseError, OSError, ValueError, RuntimeError) as error:
        print(f"News collector failed: {error}", file=sys.stderr)
        raise SystemExit(1)

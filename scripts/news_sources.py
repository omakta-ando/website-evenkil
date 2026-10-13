"""Bounded direct discovery and auditable collection; standard library only."""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import json
import codecs
import datetime as dt
import re
import threading
import time
import urllib.parse as U
import xml.etree.ElementTree as ET


def canonical_url(url):
    parts = U.urlsplit(url)
    query = U.urlencode([(k, v) for k, v in U.parse_qsl(parts.query, keep_blank_values=True)
                         if not k.lower().startswith('utm_') and k.lower() not in {'fbclid', 'gclid', 'yclid'}])
    netloc = parts.netloc.lower()
    if parts.hostname:
        netloc = netloc.replace(parts.hostname, parts.hostname.encode('idna').decode('ascii'))
    return U.urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip('/') or '/', query, ''))


class Audit:
    def __init__(self):
        self.rows = {}
        self.lock = threading.Lock()

    def event(self, source, reason, url='', **details):
        with self.lock:
            row = self.rows.setdefault(source, {'counts': {}, 'events': []})
            row['counts'][reason] = row['counts'].get(reason, 0) + 1
            # Keep every decision in this bounded run, not only successful items.
            row['events'].append({'at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'reason': reason, 'url': url, **details})

    def save(self, path, timestamp):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'version': 1, 'checkedAt': timestamp,
                                   'sources': self.rows}, ensure_ascii=False, indent=2) + '\n')


def decode_html(payload, encoding=None):
    if not encoding:
        meta_tags = b'\n'.join(re.findall(br'<meta\b[^>]*>', payload[:16384], re.I))
        match = re.search(br'charset\s*=\s*[\x22\x27]?([a-zA-Z0-9_-]+)', meta_tags, re.I)
        encoding = match.group(1).decode('ascii') if match else 'utf-8-sig'
    try:
        codecs.lookup(encoding)
    except LookupError as error:
        raise ValueError('unsupported_charset:' + encoding) from error
    return payload.decode(encoding, errors='replace')


class Page(HTMLParser):
    def __init__(self, document, base):
        super().__init__()
        self.base = base
        self.feeds, self.links, self.structured = [], [], []
        self.meta = {}
        self.anchor = None
        self.script = None
        self.article_text = ''
        self._body_parts = []
        self._skip_depth = 0
        self.feed(document)
        if not self.article_text:
            self.article_text = ' '.join(self._body_parts)[:12000]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'link' and 'alternate' in (a.get('rel') or '').split() and any(
                t in (a.get('type') or '') for t in ('rss', 'atom')):
            self.feeds.append(U.urljoin(self.base, a.get('href') or ''))
        if tag == 'meta':
            self.meta[a.get('property') or a.get('name') or a.get('itemprop')] = a.get('content', '')
        if tag == 'a':
            self.anchor = [U.urljoin(self.base, a.get('href') or ''), '']
        if tag == 'script' and a.get('type') == 'application/ld+json':
            self.script = ''
        if tag in {'script', 'style', 'svg', 'nav', 'footer', 'header', 'aside', 'noscript'}:
            self._skip_depth += 1

    def handle_data(self, data):
        if self.anchor is not None and not self._skip_depth:
            self.anchor[1] += data
        if self.script is not None:
            self.script += data
        elif not self._skip_depth and data.strip():
            self._body_parts.append(data.strip())

    def handle_endtag(self, tag):
        if tag == 'a' and self.anchor is not None:
            self.links.append(self.anchor)
            self.anchor = None
        if tag == 'script' and self.script is not None:
            try:
                parsed = json.loads(self.script)
                self.structured.append(parsed)
                for article in self.articles():
                    if article.get('articleText'):
                        self.article_text = str(article['articleText'])[:12000]
                        break
            except ValueError:
                pass
            self.script = None
        if tag in {'script', 'style', 'svg', 'nav', 'footer', 'header', 'aside', 'noscript'}:
            self._skip_depth = max(0, self._skip_depth - 1)

    def articles(self):
        def walk(value):
            if isinstance(value, list):
                for child in value:
                    yield from walk(child)
            elif isinstance(value, dict):
                types = value.get('@type', [])
                types = [types] if isinstance(types, str) else types
                if any(t in {'NewsArticle', 'Article', 'BlogPosting'} for t in types):
                    main = value.get('mainEntityOfPage', '')
                    if isinstance(main, dict):
                        main = main.get('@id', '')
                    yield {'url': U.urljoin(self.base, value.get('url') or main or self.base),
                           'title': value.get('headline', ''), 'description': value.get('description', ''),
                           'date': value.get('datePublished', ''), 'articleText': value.get('articleBody', '')}
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        yield from walk(child)
        yield from walk(self.structured)
        if self.meta.get('article:published_time'):
            yield {'url': self.base, 'title': self.meta.get('og:title', ''),
                   'description': self.meta.get('og:description', ''),
                   'date': self.meta['article:published_time']}


def rss_items(payload):
    root = ET.fromstring(payload)
    def local(tag):
        return tag.rsplit('}', 1)[-1]
    if local(root.tag) not in {'rss', 'feed', 'RDF'}:
        raise ValueError('not_rss_or_atom')
    for node in root.iter():
        if local(node.tag) not in {'item', 'entry'}:
            continue
        values = {local(c.tag): c.text or '' for c in node}
        link = values.get('link', '')
        for c in node:
            if local(c.tag) == 'link' and c.get('rel', 'alternate') == 'alternate':
                link = c.get('href') or link
        yield {'url': link, 'title': values.get('title', ''),
               'description': values.get('description') or values.get('summary') or values.get('encoded', ''),
               'date': values.get('pubDate') or values.get('published') or values.get('date', '')}


def fetch_domains(collector, domains, config, audit):
    """Visit every configured domain; explicit endpoints override autodiscovery.

    Limits apply to requests, never silently to accepted stories. A site needing
    JavaScript or a custom parser is reported, rather than marked covered.
    """
    options = config.get('directDiscovery', {})
    endpoints = {publisher['domain']: {'url': publisher['url'], 'label': publisher.get('label', publisher['domain'])}
                 for country in config.get('internationalMedia', [])
                 for publisher in country.get('publishers', []) if publisher.get('domain') and publisher.get('url')}
    endpoints.update(options.get('sources', {}))
    cutoff = collector.now_local() - collector.dt.timedelta(days=options.get('lookbackDays', 7))
    max_articles = int(options.get('maxArticlePages', 8))
    max_feeds = int(options.get('maxFeeds', 3))

    def run(domain):
        found = []
        deadline = time.monotonic() + int(options.get("sourceBudgetSeconds", 30))
        settings = endpoints.get(domain, {})
        start = settings.get('url', 'https://' + domain + '/')
        feeds = list(settings.get('feeds', []))
        visited = set()
        audit.event(domain, 'started', start)

        def get(url):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                audit.event(domain, 'source_time_limit', url)
                return None
            audit.event(domain, 'request', url)
            try:
                payload = collector.request(url, timeout=max(1, min(10, remaining)))
                audit.event(domain, 'request_ok', url)
                return payload
            except (OSError, ValueError) as error:
                audit.event(domain, 'request_failed', url, error=type(error).__name__,
                            httpStatus=getattr(error, 'code', None))
                return None

        def decode(payload):
            try:
                return decode_html(payload, settings.get('encoding'))
            except ValueError as error:
                audit.event(domain, 'invalid_encoding_fallback', detail=str(error))
                return payload.decode('utf-8-sig', errors='replace')

        def accept(raw, base):
            url = U.urljoin(base, str(raw.get('url', '')))
            host = (U.urlsplit(url).hostname or '').encode('idna').decode('ascii')
            ascii_domain = domain.encode('idna').decode('ascii')
            if U.urlsplit(url).scheme not in {'https', 'http'} or not (host == ascii_domain or host.endswith('.' + ascii_domain)):
                audit.event(domain, 'foreign_or_invalid_url', url)
                return
            url = canonical_url(url)
            published = collector.parse_date(str(raw.get('date', '')))
            item = {'id': url, 'url': url, 'title': collector.clean(str(raw.get('title', ''))),
                    'description': collector.clean(str(raw.get('description', ''))),
                    'articleText': collector.clean(str(raw.get('articleText', ''))),
                    'source': settings.get('label', domain), 'configuredSource': '1', 'auditSource': domain}
            relevance = collector.story_relevance(item)
            needs_review = collector.needs_fulltext_review(item)
            reason = ('missing_title' if not item['title'] else 'invalid_date' if not published else
                      'future_date' if published > collector.now_local() + collector.dt.timedelta(hours=6) else
                      'outside_window' if published < cutoff else
                      'editorial_exclusion' if collector.is_excluded_story(item) else
                      'irrelevant' if not relevance and not needs_review else
                      'duplicate_url' if url in visited else 'accepted')
            audit.event(domain, reason, url)
            if reason == 'accepted':
                visited.add(url)
                item['detectedRelevance'] = relevance or ''
                item['needsFullText'] = '1' if needs_review and not relevance else '0'
                item.pop('articleText', None)
                item['description'] = item['description'][:420]
                item.update(published=published.isoformat(timespec='minutes'), day=published.date().isoformat())
                found.append(item)

        page_payload = get(start)
        page = None
        if page_payload:
            # Some configured landing URLs are themselves feeds.
            try:
                for raw in rss_items(page_payload):
                    accept(raw, start)
            except (ET.ParseError, ValueError):
                page = Page(decode(page_payload), start)
                feeds.extend(page.feeds)
                for raw in page.articles():
                    accept(raw, start)
        feeds = list(dict.fromkeys(feeds))
        for feed in feeds[:max_feeds]:
            payload = get(feed)
            if payload:
                try:
                    for raw in rss_items(payload):
                        accept(raw, feed)
                except (ET.ParseError, ValueError):
                    audit.event(domain, 'invalid_feed', feed)
        if len(feeds) > max_feeds:
            audit.event(domain, 'feed_limit', start, omitted=len(feeds)-max_feeds)
        # RSS is preferred. Inspect same-site article links when no feed is available.
        if page and not found:
            links = list(dict.fromkeys(url for url, title in page.links
                if len(collector.clean(title)) >= 20 and ((U.urlsplit(url).hostname or '') == domain or (U.urlsplit(url).hostname or '').endswith('.' + domain))
                and canonical_url(url) != canonical_url(start)))
            links.sort(key=lambda url: not any(collector.is_evenki_related({'title': title}) for target, title in page.links if target == url))
            for url in links[:max_articles]:
                payload = get(url)
                if payload:
                    article = Page(decode(payload), url)
                    raws = list(article.articles())
                    if not raws:
                        audit.event(domain, 'unsupported_html_or_js', url)
                    for raw in raws:
                        accept(raw, url)
            if len(links) > max_articles:
                audit.event(domain, 'article_page_limit', start, omitted=len(links)-max_articles)
            if not links and not list(page.articles()):
                audit.event(domain, 'unsupported_html_or_js', start)
        audit.event(domain, 'completed', start, accepted=len(found))
        return found

    def safe_run(domain):
        try:
            return run(domain)
        except (OSError, ValueError, TypeError, KeyError) as error:
            audit.event(domain, 'adapter_error', error=type(error).__name__, detail=str(error)[:200])
            return []

    result = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for items in pool.map(safe_run, domains):
            result.extend(items)
    return result

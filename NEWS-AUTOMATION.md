# Telegram news automation

The scheduled GitHub Actions workflow searches focused topic groups from
`news-search-queries.json` across the full Google News RSS index. Each configured
publisher domain in `news-search-sources.json` also gets its own source-scoped
search. Requests run in a small parallel pool so one
batch cannot hide smaller outlets. Region-only terms are excluded from the
general search. EAO terms get separate
targeted searches, including configured public Telegram and VK accounts.
Public Telegram channels in the source list are also read directly from their
public web previews, in addition to Google News discovery. Configured VK walls
are read directly through the official API when the optional `VK_ACCESS_TOKEN`
GitHub Actions secret is set; without it, VK coverage uses Google News indexing
and is not guaranteed. Private posts are never read. The Ilken
Evenki-language category is searched separately and its category RSS is
checked directly. The public «Арун» news archive is scanned directly as well:
all dated posts from the last 30 days are added once, so headlines without an
Evenki keyword are not lost to Google News indexing. Duplicate publisher URLs
are skipped. The site can backfill up to 30 days of missed archive posts, while
Telegram notifications remain limited to the normal 72-hour collection window
so a backfill does not flood the channel. A source-wide archive scan does not
establish editorial accuracy; posts retain the publisher's title, short archive
blurb, date, and link.

At 12:07 and 18:07 Asia/Tbilisi, newly discovered matching stories are sent to
`@taiga_thread`. New stories from the dedicated Ilken Evenki category are also
added to `news-data.js`, with the publisher's title, a short excerpt, and a link
to the original article; GitHub Pages then serves those cards from the site
feed. At 19:07 the workflow posts a digest of stories found that day. Empty
digests are skipped.

The publisher-specific searches are discovery queries, not direct crawls of
every page on each site. Coverage depends on Google News indexing and RSS
results; a headline match is not editorial verification. Recent relevant
results from configured publisher domains, the dedicated Ilken Evenki
category, and the Арун archive are eligible for the public site feed. Full
article text is never copied. Where Google News provides a redirect,
the collector follows it to the publisher URL before posting.

Repository prerequisites:

- GitHub Actions secret `TELEGRAM_BOT_TOKEN` containing the BotFather token.
- The bot added to the channel as an administrator with permission to post.
- The public channel username `@taiga_thread` set in
  `.github/workflows/telegram-news.yml`.
- Optional GitHub Actions secret `VK_ACCESS_TOKEN` for direct reading of public
  VK walls in the configured source list. Google News indexed search continues
  without this token.

After committing and pushing the workflow to the repository's default branch,
enable Actions for the repository. Run it manually from the Actions tab with
mode `collect` to publish newly discovered stories, or `digest` to publish the
current day's roundup. Scheduled runs can be delayed by GitHub during periods
of high Actions load.

## Direct discovery and diagnostics

Every unique configured publisher domain (including international publishers)
now receives a direct HTTPS landing-page request alongside the existing Google
News searches. RSS/Atom links advertised with `rel=alternate` are discovered
and parsed, including namespaced dates. When feeds yield no matching stories,
same-site linked pages are inspected for `NewsArticle`, `Article`, or
`BlogPosting` JSON-LD and Open Graph publication metadata. This reads only
publisher headlines, dates, short descriptions, and links. It does not execute
JavaScript or bypass authentication/captchas. A successful page request is not
proof of complete source coverage.

`news-search-sources.json.directDiscovery` controls the seven-day site backfill,
article-page limit (8), feed limit (3), and per-domain time budget (30 seconds).
An optional `sources` object maps domains to explicit endpoints, for example:

```json
{
  "example.org": {
    "url": "https://example.org/news/",
    "feeds": ["https://example.org/news/rss.xml"],
    "label": "Publisher name",
    "encoding": "utf-8"
  }
}
```

A site without an advertised RSS feed or structured article dates needs an
explicit endpoint or a publisher-specific parser. Article links are bounded:
this is not an exhaustive crawl of every archive page. Limits, unsupported HTML
(including possible JS shells), HTTP failures, invalid/future dates, irrelevant
items, exclusions, and duplicates are recorded instead of silently implying
coverage. Dates without a timezone use UTC for ISO/RSS and Asia/Tbilisi for
Russian dates. Publication dates are never invented from the collection time.

Public Telegram previews now paginate backwards until the 72-hour cutoff or
8 pages. VK walls paginate up to 800 posts; old pinned posts do not terminate
reading, public/club numeric IDs use `owner_id`, and public repost text is
considered. Missing `VK_ACCESS_TOKEN` and API errors are recorded per account.
Private/restricted posts and media-only text still require another permitted
source. Google News remains enabled for every configured publisher/account.

`local-entities` queries and `relevanceEntities` add explicit names of settlements
and organizations. Settlement matches require a configured topical expression,
such as school, culture, community or reindeer herding; weather or a region name
alone does not qualify. These records are classified as `context`, preserving
existing category names. Add missed-news examples by extending these entries
and adding a regression fixture. Already added site stories were used as controls, including Telegram post
`evenkya_life/12658` (books and the Evenki festival). Its full-text match previously
disappeared after shortening the excerpt. The retained relevance decision now
survives shortening and is covered by a saved regression fixture. Complete recall
relative to all manually found publications remains unmeasured.

The dedicated Arun and Ilken categories retain their keyword exception through
collection, site storage, pending Telegram and digest-state loading. Incoming
URLs are normalized for fragments and advertising tracking parameters; meaningful
query parameters are preserved. URL delivery history supplements legacy GUIDs.
Google redirects that remain unresolved cannot reliably be matched to a direct
publisher URL and may still duplicate it; no fuzzy headline deduplication was added.

Run a non-publishing audit with:

```sh
python3 scripts/telegram_news.py --audit-only
python3 -m unittest discover -s tests -v
```

Audit-only writes `data/news-source-audit.json`, without modifying `news-data.js`,
Telegram state or sending messages. The report describes the latest run; scheduled
collection uploads it as a 30-day GitHub Actions artifact, even on failure. Source
keys include domains, social-account IDs, named adapters and Google queries. HTTP
success, source acceptance and final site/Telegram decisions are separate events.
API tokens and request bodies are not included. In normal collection, the existing
four-per-source Telegram limit is preserved and reported; it never limits the site
feed. The workflow's collection timeout is 30 minutes and regression tests run
before collection. Existing notify-after-site-publication and digest steps remain.

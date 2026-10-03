# Telegram news automation

The scheduled GitHub Actions workflow searches the query groups in
`news-search-queries.json` through Google News RSS, except for region-only and
Ilken-specific queries. It searches both the general news index and batches of
the media domains in `news-search-sources.json`. EAO terms get separate
targeted searches, including configured public Telegram and VK accounts.
Social posts are discovered through Google News indexing, not by reading
private or complete social feeds, so coverage is not guaranteed. The Ilken
Evenki-language category is searched separately and its category RSS is
checked directly. The public «Арун» news archive is scanned directly as well:
all dated posts from the last 30 days are added once, so headlines without an
Evenki keyword are not lost to Google News indexing. Duplicate publisher URLs
are skipped. The site can backfill up to 30 days of missed archive posts, while
Telegram notifications remain limited to the normal 36-hour collection window
so a backfill does not flood the channel. A source-wide archive scan does not
establish editorial accuracy; posts retain the publisher's title, short archive
blurb, date, and link.

At 12:00 and 18:00 Asia/Tbilisi, newly discovered matching stories are sent to
`@taiga_thread`. New stories from the dedicated Ilken Evenki category are also
added to `news-data.js`, with the publisher's title, a short excerpt, and a link
to the original article; GitHub Pages then serves those cards from the site
feed. At 19:00 the workflow posts a digest of stories found that day. Empty
digests are skipped.

The general search is a discovery aid, not a complete monitor of every outlet
in the media directory. Coverage depends on Google News indexing and RSS
results; a headline match is not editorial verification. Only the dedicated
Ilken Evenki category is configured for automatic addition to the public site
feed. Full article text is never copied. Where Google News provides a redirect,
the collector follows it to the publisher URL before posting.

Repository prerequisites:

- GitHub Actions secret `TELEGRAM_BOT_TOKEN` containing the BotFather token.
- The bot added to the channel as an administrator with permission to post.
- The public channel username `@taiga_thread` set in
  `.github/workflows/telegram-news.yml`.

After committing and pushing the workflow to the repository's default branch,
enable Actions for the repository. Run it manually from the Actions tab with
mode `collect` to publish newly discovered stories, or `digest` to publish the
current day's roundup. Scheduled runs can be delayed by GitHub during periods
of high Actions load.

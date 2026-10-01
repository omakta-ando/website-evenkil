# Telegram news automation

The scheduled GitHub Actions workflow searches the query groups in
`news-search-queries.json` through Google News RSS, except for region-only
queries. It searches both the general news index and batches of the 93 domains
extracted from the project's media list in `news-search-sources.json`. It
checks recent headlines at 12:00 and 18:00 Asia/Tbilisi and posts new matching
stories to `@taiga_thread`. At 19:00 it posts a digest of stories found that
day, with links to publishers. Empty digests are skipped.

The search is a discovery aid, not a complete monitor of every outlet in the
media directory. Coverage depends on Google News indexing and RSS results; a
headline match is not editorial verification. Outlets without Google News
coverage need direct feeds or a separate connector. Where Google News provides
a redirect, the collector follows it to the publisher URL before posting.

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

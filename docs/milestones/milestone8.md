# Milestone 8 — Multi-Source Ingestion

> Parent plan: [`../vision.md`](../vision.md)
> Predecessor: [`milestone7.md`](./milestone7.md)
> Owner: 1 engineer · Timebox: ~5 days · Status: 🔲 Not started

---

## 1. Goal

LinkedIn is just one signal. Bring in RSS/newsletter articles, Twitter/X bookmarks, Hacker News saved items, and Reddit saved posts into the same unified `Post` table so the knowledge graph reflects your full information diet — not just one platform.

Every source shares the same pipeline (enrich → classify → embed → graph → vault) with source-specific metadata preserved.

---

## 2. Exit Criteria

- [ ] `Post.platform` field already exists; all new sources use it (`rss`, `twitter`, `hackernews`, `reddit`).
- [ ] `SourceConnector` abstract base class: `fetch_new(since_urn?) -> list[RawPost]`.
- [ ] **RSS/Newsletter connector**: given a list of feed URLs (from `SG_RSS_FEEDS` env var, comma-separated), fetches new articles since last run using `feedparser`. Creates posts with `platform="rss"`.
- [ ] **Hacker News connector**: fetches saved/upvoted items via HN Firebase API (`https://hacker-news.firebaseio.com/`). `platform="hackernews"`.
- [ ] **Reddit connector**: fetches saved posts via PRAW. `platform="reddit"`. Requires `SG_REDDIT_CLIENT_ID`, `SG_REDDIT_CLIENT_SECRET`, `SG_REDDIT_USERNAME`, `SG_REDDIT_PASSWORD`.
- [ ] **Twitter/X bookmarks connector**: Playwright-based (X doesn't have a public bookmarks API). Authenticates via `SG_X_EMAIL` / `SG_X_PASSWORD`, scrapes bookmarks page. `platform="twitter"`.
- [ ] `sg ingest --source rss|hackernews|reddit|twitter|linkedin` runs specific connector.
- [ ] `sg ingest --all-sources` runs all configured connectors.
- [ ] All sources feed into the same downstream pipeline without modification.
- [ ] `sg status` shows per-source post counts.
- [ ] `ruff check` passes.

---

## 3. Action Points

### Day 1 — Source Connector Interface + RSS

- **AP-8.1** `socialgraph/ingest/base.py`: `SourceConnector` ABC with `source_id: str`, `fetch_new(db_session) -> list[RawPost]` async method. `RawPost` dataclass: `urn, platform, author, content, source_url, date_raw, subtitle?`.
- **AP-8.2** `socialgraph/ingest/connectors/rss.py`: `RSSConnector(SourceConnector)`.
  - Add `feedparser` dependency.
  - `fetch_new()`: read `SG_RSS_FEEDS` (comma-separated URLs), parse feeds, create `RawPost` per entry. URN = `rss:{sha256(entry.link)[:12]}`.
  - Skip entries already in DB (URN exists).
- **AP-8.3** `SG_RSS_FEEDS` env var support in `settings.py`.
- **AP-8.4** Unit test: mock feedparser response, assert correct `RawPost` objects returned.

### Day 2 — Hacker News + Reddit

- **AP-8.5** `socialgraph/ingest/connectors/hackernews.py`: `HackerNewsConnector`.
  - Fetch user upvoted stories via `https://hacker-news.firebaseio.com/v0/user/{username}/submitted.json` or saved items.
  - `SG_HN_USERNAME` env var.
  - URN = `hn:{item_id}`. Content = story title + URL.
- **AP-8.6** `socialgraph/ingest/connectors/reddit.py`: `RedditConnector`.
  - Add `praw` dependency.
  - Fetch `reddit.user.me().saved(limit=500)`. Filter to `Submission` type.
  - URN = `reddit:{submission.id}`. Content = title + selftext (truncated to 2000 chars).
  - `SG_REDDIT_*` env vars.
- **AP-8.7** Unit tests for both connectors with mocked API responses.

### Day 3 — Twitter/X Bookmarks

- **AP-8.8** `socialgraph/ingest/connectors/twitter.py`: `TwitterConnector` using Playwright.
  - Authenticate via `SG_X_EMAIL` / `SG_X_PASSWORD`; save session to `.socialgraph/x_session.json`.
  - Scrape `https://x.com/i/bookmarks`: scroll, extract tweet text + author + URL.
  - URN = `twitter:{tweet_id_from_url}`.
  - Reuses Playwright session management pattern from LinkedIn scraper.
- **AP-8.9** `SG_X_EMAIL`, `SG_X_PASSWORD` env vars.
- **AP-8.10** Graceful auth failure: if login fails, log `ingest.connector_auth_failed` at ERROR, skip connector, continue with others.

### Day 4 — CLI Integration + Source Registry

- **AP-8.11** `socialgraph/ingest/registry.py`: `SourceRegistry` — registers all connectors, instantiates based on which env vars are set.
- **AP-8.12** `IngestAgent.run()`: accept `source_filter: list[str] | None`. If None, run all registered connectors. If set, run only matching `source_id`.
- **AP-8.13** `sg ingest --source NAME` and `sg ingest --all-sources` CLI flags.
- **AP-8.14** `sg status` per-source breakdown: `linkedin: 1508, rss: 42, hackernews: 17, ...`.

### Day 5 — E2E + Vault Source Labelling

- **AP-8.15** Vault notes: `platform:` frontmatter field already in `render_post_note()`. Verify RSS/HN/Reddit posts render correctly.
- **AP-8.16** Topic MOC files: show per-platform breakdown in topic note (e.g., "LinkedIn: 45, RSS: 12").
- **AP-8.17** E2E: configure a real RSS feed in `.env`, run `sg ingest --source rss`, assert new posts created with `platform="rss"`, run classify → vault-write, verify vault notes created.

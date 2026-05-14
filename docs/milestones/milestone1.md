# Milestone 1 — Deep Enrichment

> Parent plan: [`../vision.md`](../vision.md)
> Predecessor: [`milestone0.md`](./milestone0.md)
> Owner: 1 engineer · Timebox: ~5 days · Status: 🔲 Not started

---

## 1. Goal

Make every post *rich*: fetch and understand all external links referenced in post bodies, scrape LinkedIn comments for each post and extract URLs from those too, and use vLLM to summarize fetched article content. By the end of M1, the enrichment pipeline runs end-to-end for all 1508 posts, comments are in the DB, and every external link has a human-readable summary.

This milestone does **not** change the classification or graph layers — only the enrichment depth going into them.

---

## 2. Exit Criteria

- [ ] `sg enrich` runs to completion on all 1508 posts (`status: ingested → enriched`).
- [ ] All non-social URLs in post bodies are fetched; `ExternalLink` rows have `fetch_status="ok"` with `title`, `description`, `body_excerpt` populated.
- [ ] vLLM `summarize_content` task is wired and called: each fetched article's `body_excerpt` is replaced by a 2–3 sentence LLM summary stored in `ExternalLink.body_excerpt`.
- [ ] Playwright comment scraper implemented: for each post, authenticate with LinkedIn session cookie, navigate to post URL, extract top `SG_MAX_COMMENTS` comments (author + text + has_external_url).
- [ ] Comment rows inserted into `Comment` table linked to their parent post.
- [ ] URLs found in comment text are fetched and stored as `PostExternalLink(context="comment")`.
- [ ] `sg status` shows enriched post count, total external links fetched, total comments scraped.
- [ ] Vault notes updated: `external_links:` frontmatter lists article titles + summaries; `comments_notable: true` when comments contain external URLs.
- [ ] Re-running `sg enrich` is idempotent: already-fetched links skip refetch; already-scraped comments skip re-scrape.
- [ ] `ruff check` passes; existing 29 unit tests still pass.

---

## 3. Action Points

### Day 1 — Wire `summarize_content` into EnrichAgent

- **AP-1.1** In `socialgraph/agents/enrich_agent.py`, after `_fetch_link()` stores `body_excerpt` from trafilatura, call `router.route("summarize_content")` (vLLM batch) to replace the raw excerpt with a 2–3 sentence summary. Batch all links per-post before committing.
- **AP-1.2** Add `summarize_content` prompt to `socialgraph/llm/prompts.py`: system = "Summarize the following article in 2-3 sentences focusing on the key insight. Be concise."; user = article text (truncated to 4000 chars).
- **AP-1.3** Add `response_format=None` (plain text) for summarize task — no JSON needed.
- **AP-1.4** Unit test: mock vLLM batch response, assert `body_excerpt` is updated with summary, not raw text.
- **AP-1.5** Integration smoke: run `sg enrich` on 5 posts, verify `ExternalLink.body_excerpt` is non-empty and shorter than raw trafilatura output.

### Day 2 — Idempotency + Status Tracking

- **AP-1.6** Add `enrich_attempted_at` timestamp column to `Post` table (`alembic/versions/0010_enrich_timestamp.py`).
- **AP-1.7** Enrich agent: skip posts where `enrich_attempted_at` is set (already attempted). Reset via `sg enrich --force`.
- **AP-1.8** Add `sg status` enrichment breakdown: posts enriched, links fetched (ok/failed), avg links per post.
- **AP-1.9** Error handling: if link fetch fails (404, timeout, robots.txt block), set `fetch_status="failed"` and continue — never abort the whole batch.

### Day 3 — LinkedIn Comment Scraper

- **AP-1.10** Create `socialgraph/ingest/comment_scraper.py`: `CommentScraper` class using Playwright.
  - `authenticate(page, email, password)`: login flow, save session to `.socialgraph/linkedin_session.json`.
  - `scrape_post_comments(page, post_url, max_comments)` → `list[CommentData]` with `author, text, rank`.
  - Reuse existing `playwright_client.py` session management pattern.
- **AP-1.11** `CommentData` Pydantic model: `author: str, text: str, rank: int, has_external_url: bool`.
- **AP-1.12** `has_external_url` detection: regex scan of comment text for `https?://` not pointing to `linkedin.com`.
- **AP-1.13** Repo method `add_comments(post_id, comments: list[CommentData])`: bulk insert with upsert on `(post_id, rank)`.

### Day 4 — Wire Comment Scraping into EnrichAgent

- **AP-1.14** `EnrichAgent._enrich_post()`: after link fetching, call `CommentScraper.scrape_post_comments()` using `settings.max_comments`. Store results via `repo.add_comments()`.
- **AP-1.15** After scraping comments, extract URLs from comment text via `_extract_urls()`, filter via `should_fetch_url()`, fetch each, create `PostExternalLink(context="comment")`.
- **AP-1.16** `settings.py`: ensure `SG_PLAYWRIGHT_HEADLESS` is respected by `CommentScraper`.
- **AP-1.17** Graceful degradation: if Playwright fails for a post (post deleted, auth expired), log `enrich.comment_scrape_failed` at WARNING and continue — don't fail the post.

### Day 5 — Vault Update + E2E Verification

- **AP-1.18** Update `vault_write_agent.py` and `render_post_note()`: include `comments` section in note if comments exist; list notable comments (those with `has_external_url=True`) with author + text snippet.
- **AP-1.19** Update post note `external_links:` frontmatter to include link summary from `body_excerpt` (truncated to 100 chars for frontmatter readability).
- **AP-1.20** Run full pipeline on all 1508 posts: `sg enrich && sg classify && sg build-graph && sg vault-write`.
- **AP-1.21** Verify: `sg status` shows enriched count = 1508; spot-check 5 vault notes for link summaries and comment sections.

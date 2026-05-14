# Milestone 6 — Live Ingestion & Scheduling

> Parent plan: [`../vision.md`](../vision.md)
> Predecessor: [`milestone5.md`](./milestone5.md)
> Owner: 1 engineer · Timebox: ~3 days · Status: 🔲 Not started

---

## 1. Goal

Turn social-graph from a one-shot batch tool into a **continuously self-updating system**. A scheduler runs the full pipeline on a configurable cadence, detecting new LinkedIn saves automatically via Playwright, processing only the delta, and keeping the MCP server's data fresh without manual intervention.

---

## 2. Exit Criteria

- [ ] Playwright-based LinkedIn scraper: detects new saved posts vs already-ingested URNs, returns only new posts.
- [ ] `sg ingest --live` mode: scrapes LinkedIn, inserts new posts, exits — does not re-process existing posts.
- [ ] Incremental pipeline: `sg run --incremental` only processes posts that have not yet completed each stage (existing checkpoint logic extended).
- [ ] `sg schedule start [--interval-hours N]` starts APScheduler background daemon; runs `ingest --live && enrich && classify && embed && build-graph && vault-write` on schedule.
- [ ] `sg schedule status` shows: last run time, next run time, last run result (N new posts processed), daemon PID.
- [ ] `sg schedule stop` cleanly shuts down daemon.
- [ ] Schedule state persisted in `.socialgraph/schedule.json` (survives restarts).
- [ ] Duplicate detection: posts with already-ingested URN are skipped silently.
- [ ] `ruff check` passes.

---

## 3. Action Points

### Day 1 — Incremental Ingest + Deduplication

- **AP-6.1** `socialgraph/ingest/live_scraper.py`: `LinkedInLiveScraper` using Playwright.
  - `scrape_saved_posts(page, already_known_urns: set[str], max_posts=500)` → `list[RawPost]`.
  - Scrolls through LinkedIn saved posts list, extracts URN + content + author. Stops when it encounters an already-known URN (relies on recency order).
  - Reuses LinkedIn session from `.socialgraph/linkedin_session.json`.
- **AP-6.2** `IngestAgent`: add `live_mode: bool` parameter. In live mode, fetch all known URNs from DB first, pass to scraper as `already_known_urns`, only insert new ones.
- **AP-6.3** `sg ingest --live` CLI flag.
- **AP-6.4** Upsert protection: `repo.create_post()` uses `INSERT OR IGNORE` on `urn` unique constraint — no duplicates even if scraper re-sees a post.

### Day 2 — Scheduler Daemon

- **AP-6.5** Add `apscheduler>=3.10` to `pyproject.toml`.
- **AP-6.6** `socialgraph/runner/scheduler.py`: `SchedulerDaemon`.
  - `start(interval_hours, settings)`: creates APScheduler `BackgroundScheduler`, adds `IntervalTrigger`, runs pipeline function.
  - `stop()`: graceful shutdown.
  - Writes PID + next run time to `.socialgraph/schedule.json` on each tick.
- **AP-6.7** Pipeline function for scheduler: `run_incremental_pipeline(settings)` — async, runs all stages in order, only processes posts not yet at each stage's completion status.
- **AP-6.8** `sg schedule start [--interval-hours N]` / `sg schedule stop` / `sg schedule status` CLI commands.
- **AP-6.9** `SG_SCHEDULE_INTERVAL_HOURS` env var (default: 6).

### Day 3 — Robustness + E2E

- **AP-6.10** Scheduler error handling: if any stage fails, log error, mark run as failed in `schedule.json`, continue to next scheduled run — never crash the daemon.
- **AP-6.11** LinkedIn session refresh: if Playwright gets a login redirect, re-authenticate with stored credentials, retry once.
- **AP-6.12** `sg status` extended: show scheduler status section (running / stopped, last run, N posts in queue).
- **AP-6.13** E2E test: mock LinkedIn scraper returning 3 new posts, run incremental pipeline, assert 3 new posts reach `graphed` status.

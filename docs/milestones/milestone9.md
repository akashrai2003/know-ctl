# Milestone 9 — AI Analyst & Digest Agent

> Parent plan: [`../vision.md`](../vision.md)
> Predecessor: [`milestone8.md`](./milestone8.md)
> Owner: 1 engineer · Timebox: ~4 days · Status: 🔲 Not started

---

## 1. Goal

The knowledge graph starts talking back. Use Groq `synthesize_insights` to generate weekly digests, identify knowledge gaps, rank your reading queue by relevance, and surface trends you might have missed. This is the "second brain" payoff — the system proactively tells you what it knows and what you're missing.

---

## 2. Exit Criteria

- [ ] `sg digest [--period week|month] [--topic TOPIC]` generates a narrative markdown report via Groq and saves it to `.socialgraph/digests/YYYY-MM-DD.md` and appends to vault `_digest.md`.
- [ ] Digest covers: top themes in the period, notable new authors, top linked articles, fastest-growing topics.
- [ ] `sg gaps` command: Groq analyzes topic density and post content → suggests underrepresented areas ("You have 80 posts on LLMs but almost nothing on evals or interpretability").
- [ ] `sg queue [--top N]` reading queue: ranks all `ExternalLink` rows not yet surfaced in a digest by relevance to your top-3 most-saved topics. Output as ordered markdown list.
- [ ] `sg trends [--months N]` topic trend report: which topics are growing vs declining based on `date_raw`; Groq writes a 2-paragraph narrative summary.
- [ ] Digest results cached: same period + same post set → same digest (SHA-256 keyed in `.socialgraph/digest_cache.json`). Never re-calls Groq for unchanged windows.
- [ ] All commands output to stdout (markdown) and optionally `--save` to vault.
- [ ] `ruff check` passes.

---

## 3. Action Points

### Day 1 — DigestAgent Core

- **AP-9.1** `socialgraph/agents/digest_agent.py`: `DigestAgent.run(ctx, period_days, topic_filter?)`.
  - Fetch posts where `created_at >= now - period_days`.
  - Group by topic. For each group, build content snippet bundle (post author + first 200 chars, max 20 posts per topic).
  - Build `synthesize_insights` prompt: persona = "expert knowledge curator"; content = topic bundles; ask for JSON: `{"themes": [...], "notable_authors": [...], "top_articles": [...], "fastest_growing_topics": [...], "narrative": "..."}`.
  - Call Groq `synthesize_insights`.
- **AP-9.2** `synthesize_insights` prompt in `socialgraph/llm/prompts.py`.
- **AP-9.3** Cache layer: `DigestCache` in `socialgraph/agents/digest_agent.py`. Key = SHA-256 of (period_days + sorted post URNs). Read/write `.socialgraph/digest_cache.json`.
- **AP-9.4** Render digest as markdown: `render_digest(result, period, generated_at)` in `socialgraph/knowledge/obsidian.py`.
- **AP-9.5** `sg digest` CLI command with `--period`, `--topic`, `--save` flags.

### Day 2 — Gap Analysis Agent

- **AP-9.6** `socialgraph/agents/gap_agent.py`: `GapAgent.run(ctx)`.
  - Build topic density map: for each topic, count posts + unique authors + date range span.
  - Also extract top-20 most-linked external domains (signals what kind of content you consume).
  - Build Groq prompt: "Given this topic distribution and reading pattern, what knowledge areas seem underrepresented? What topics naturally adjacent to these should I explore more?" → JSON: `{"gaps": [{"area": ..., "rationale": ..., "suggested_topics": [...]}]}`.
- **AP-9.7** `sg gaps [--top N]` CLI command: prints gap analysis as a numbered list with rationale.
- **AP-9.8** Gaps cached in `.socialgraph/gaps_cache.json` (keyed by post count + topic distribution hash — invalidate when new posts are added).

### Day 3 — Reading Queue + Trends

- **AP-9.9** `socialgraph/agents/queue_agent.py`: `ReadingQueueAgent.run(ctx, top_n)`.
  - Fetch all `ExternalLink` rows with `fetch_status="ok"` and non-empty `body_excerpt`.
  - Determine user's top-3 topics by post count.
  - Embed each link's summary (reuse M3 embeddings if already computed, else embed on the fly).
  - Score each link by cosine similarity to centroid of top-3 topic embeddings.
  - Return top-N ranked list.
- **AP-9.10** `sg queue [--top N]` CLI command: prints ranked reading list as markdown (title + URL + topic match score).
- **AP-9.11** `socialgraph/agents/trends_agent.py`: `TrendsAgent.run(ctx, months)`.
  - Use `GraphAnalytics.temporal_trend()` (M4) to get per-topic monthly counts.
  - Compute MoM growth rate for each topic over the window.
  - Pass top growing + top declining topics to Groq `synthesize_insights` (brief mode) → 2-paragraph narrative.
- **AP-9.12** `sg trends [--months N]` CLI command: prints trend table + narrative.

### Day 4 — Vault Integration + Scheduling

- **AP-9.13** `VaultWriteAgent`: append latest digest to `_digest.md` in vault root (create if not exists; prepend new digest at top).
- **AP-9.14** Scheduler (M6 daemon): after each incremental pipeline run, auto-generate weekly digest if last digest is >7 days old.
- **AP-9.15** MCP server (M5): `get_weekly_digest` tool now backed by `DigestAgent` (with cache). `get_gaps` tool calls `GapAgent`.
- **AP-9.16** E2E: run `sg digest --period week`, assert output contains `themes` and `narrative` sections; run `sg gaps`, assert at least 1 gap returned; run `sg queue --top 10`, assert 10 links returned.

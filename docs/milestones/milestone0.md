# Milestone 0 — Foundation

> Parent plan: [`../vision.md`](../vision.md)
> Owner: 1 engineer · Timebox: completed · Status: ✅ Done

---

## 1. Goal

Stand up the full project skeleton and run the first end-to-end pipeline on 1508 real LinkedIn saved posts. By the end of M0 the pipeline runs ingest → classify → graph-build → vault-write with a 19-topic canonical taxonomy, structured logging, and Groq model fallback.

---

## 2. Exit Criteria

- [x] `sg init` creates workspace `.socialgraph/` (SQLite DB, logs dir).
- [x] `sg ingest --json linkedin_saved_posts.json` persists 1508 posts (`status=ingested`).
- [x] 19-topic taxonomy in `topic_taxonomy.json` with rich aliases loaded into DB.
- [x] `sg classify` classifies all 1508 posts via vLLM batch (0 failed).
- [x] `sg build-graph` produces 1508 GraphNode rows.
- [x] `sg vault-write` writes 1529 Obsidian `.md` files to vault path.
- [x] Groq fallback chain: primary → `llama-4-scout-17b` → `qwen3-32b` on rate limit.
- [x] Structured logging: console (ISO timestamps) + rotating JSON file at `.socialgraph/logs/socialgraph.log`.
- [x] LLM observability: `llm.request` / `llm.response` / `llm.batch_request` / `llm.batch_response` events with latency, token counts, and prompt preview logged on every call.
- [x] `ruff check` passes clean across entire package.
- [x] 29/29 unit tests pass.

---

## 3. What Was Built

### Pipeline
`ingest` → `classify` → `graph_build` → `vault_write`

Note: `enrich` stage exists and is scaffolded but was not run — posts were classified directly from `ingested` status.

### LLM Usage
- **vLLM Qwen3.5-9B** (batch): `classify_post_topics` — only task currently active.
- **Groq llama-3.3-70b** (single): fallback when vLLM batch returns empty for a post.
- All other router tasks (`synthesize_taxonomy`, `build_graph_structure`, `summarize_content`, etc.) are defined in `router.py` but not yet called by any agent.

### Known gaps going into M1
- `sg enrich` has never been run — no link fetching, no article summaries.
- `Comment` table exists but is always empty — no Playwright comment scraping.
- `summarize_content`, `synthesize_taxonomy`, `build_graph_structure` tasks defined but unused.
- Vault `related_posts:` frontmatter is empty — no semantic similarity.

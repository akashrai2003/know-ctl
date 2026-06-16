# Product Requirements Document — social-graph

> Automa test-generation intake document.
> This document defines what the system does, its components, and the acceptance criteria that
> automated tests should verify.

---

## 1. Product Overview

**social-graph** is a personal knowledge-graph pipeline that ingests LinkedIn saved posts, enriches
them with external article content and comments, classifies them into a topic taxonomy, builds a
navigable knowledge graph, and exports everything as an Obsidian vault of Markdown notes.

The system is driven by a CLI (`sg`) and a pipeline orchestrator that runs five stages in sequence:

```
ingest → enrich → classify → graph_build → vault_write
```

Data is persisted in a SQLite database (SQLAlchemy ORM, async). LLM tasks use two providers:
- **vLLM** (self-hosted, OpenAI-compatible) — high-volume batch classification and summarization
- **Groq** (API) — taxonomy synthesis, subtopic merging, and graph edge inference

---

## 2. Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| Async runtime | asyncio + SQLAlchemy async |
| Database | SQLite via SQLAlchemy ORM (async) |
| HTTP client | httpx (async) |
| Browser automation | Playwright (Chromium, headless) |
| HTML extraction | trafilatura, BeautifulSoup4 (lxml) |
| LLM (small) | vLLM server — Qwen3.5-9B-FP8 via OpenAI-compat API |
| LLM (large) | Groq — llama-3.3-70b-versatile (with fallback chain) |
| Config | pydantic-settings (env prefix `SG_`) |
| Logging | structlog |
| CLI | Click |
| Test framework | pytest + pytest-asyncio |

---

## 3. Domain Models

### 3.1 Post
Primary entity. Represents one saved LinkedIn post.

| Field | Type | Description |
|-------|------|-------------|
| `id` | int PK | Auto-incremented |
| `urn` | str UNIQUE | LinkedIn URN (e.g. `urn:li:activity:1234`) |
| `platform` | str | Source platform; default `"linkedin"` |
| `author` | str\|None | Author display name |
| `subtitle` | str\|None | Author's headline/subtitle |
| `date_raw` | str\|None | Raw date string from source |
| `content` | str | Full post text |
| `source_url` | str\|None | Original URL of the post |
| `status` | str | Pipeline stage: `pending → ingested → enriched → classified → graphed → ok` |
| `comments_fetched` | bool | Whether Playwright comment scraping ran |
| `title` | str\|None | LLM-generated short title (set by SubtopicAgent) |
| `summary` | str\|None | LLM-generated summary (set by SubtopicAgent) |

### 3.2 Topic
Canonical topic in the taxonomy.

| Field | Type | Description |
|-------|------|-------------|
| `id` | int PK | |
| `name` | str UNIQUE | Canonical topic name |
| `description` | str\|None | Human-readable description |
| `aliases_json` | str | JSON array of alternative names |

### 3.3 PostTopic
Many-to-many: which topics a post belongs to.

| Field | Type | Description |
|-------|------|-------------|
| `post_id` | FK → Post | |
| `topic_id` | FK → Topic | |
| `confidence_score` | float | 0.0–1.0 |
| `confidence_tag` | str | `"EXTRACTED"` (≥0.8) or `"INFERRED"` (<0.8) |

### 3.4 PostSubtopic
Fine-grained sub-classification within a topic.

| Field | Type | Description |
|-------|------|-------------|
| `post_id` | FK → Post | |
| `topic_id` | FK → Topic | |
| `subtopic_name` | str | Free-text subtopic label |

### 3.5 ExternalLink
External URL encountered in a post body or comment.

| Field | Type | Description |
|-------|------|-------------|
| `url` | str UNIQUE | The full URL |
| `title` | str\|None | og:title or `<title>` |
| `description` | str\|None | og:description |
| `body_excerpt` | str\|None | Extracted article text (up to 5000 chars) |
| `ai_summary` | str\|None | LLM-generated 2–3 sentence summary |
| `fetch_status` | str | `pending → fetching → ok / failed / skipped` |
| `error_reason` | str\|None | Error code if fetch failed |

### 3.6 PostExternalLink
Many-to-many: Post ↔ ExternalLink with context.

| Field | Type | Description |
|-------|------|-------------|
| `post_id` | FK → Post | |
| `external_link_id` | FK → ExternalLink | |
| `context` | str | `"body"` or `"comment"` |
| `comment_id` | FK → Comment\|None | Set when `context="comment"` |

### 3.7 Comment
LinkedIn comment on a post.

| Field | Type | Description |
|-------|------|-------------|
| `post_id` | FK → Post | |
| `author` | str\|None | Commenter display name |
| `text` | str | Comment body |
| `has_external_url` | bool | True if the comment text contains non-LinkedIn URLs |
| `rank` | int | Position/ordering within thread |

### 3.8 GraphNode
Node in the knowledge graph.

| Field | Type | Description |
|-------|------|-------------|
| `node_id` | str UNIQUE | Slug identifier |
| `node_type` | str | `"post"` or `"topic"` |
| `label` | str | Display label |
| `community` | str\|None | Community cluster ID |
| `meta_json` | str | JSON blob of extra metadata |

### 3.9 GraphEdge
Directed edge in the knowledge graph.

| Field | Type | Description |
|-------|------|-------------|
| `source_node_id` | FK → GraphNode | |
| `target_node_id` | FK → GraphNode | |
| `relation` | str | e.g. `"conceptually_related_to"` |
| `confidence_score` | float | 0.0–1.0 |
| `confidence_tag` | str | `"EXTRACTED"` or `"INFERRED"` |

### 3.10 Author
Denormalized author table (rebuilt on each `vault_write` run).

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Display name |
| `slug` | str UNIQUE | URL-safe slug |
| `subtitle` | str\|None | Author's professional headline |
| `platform` | str | `"linkedin"` |
| `post_count` | int | Number of saved posts |

### 3.11 PipelineRun / StageCheckpoint
Audit trail for each pipeline execution.

- `PipelineRun`: one record per `sg run` invocation (`run_id`, `status`, `started_at`, `completed_at`)
- `StageCheckpoint`: one record per stage per run with `input_hash` for idempotency

---

## 4. Pipeline Stages

### Stage 1 — Ingest (`IngestAgent`)

**Purpose**: Load raw posts from a JSON file (LinkedIn export) or Playwright live scrape into the DB.

**Acceptance Criteria**:

- AC-1.1: Given a valid `linkedin_saved_posts.json`, each post object is mapped to a `Post` row with `status="ingested"`.
- AC-1.2: Posts with a URN already present in the DB are skipped (idempotent); `skipped` count is returned in `StageOutput`.
- AC-1.3: `IngestAgent` raises `ValueError` when `live_mode=False` and `json_path` is `None`.
- AC-1.4: All required fields (`urn`, `platform`, `content`) are non-empty after ingest.
- AC-1.5: `StageOutput.processed` equals the number of newly created `Post` rows; `StageOutput.skipped` equals the number already-existing rows.

### Stage 2 — Enrich (`EnrichAgent`)

**Purpose**: Fetch all external URLs in post bodies and comments; extract article text with trafilatura; run Playwright fallback for JS-rendered pages; batch-summarize fetched links with vLLM.

**Acceptance Criteria**:

- AC-2.1: `should_fetch_url(url)` returns `False` for LinkedIn, Twitter/X, Facebook, Instagram URLs; returns `True` for other HTTP/HTTPS URLs.
- AC-2.2: `_extract_urls(text)` correctly parses all `https?://` URLs from a text string, strips trailing punctuation (`)`, `.`, `,`, `;`), and deduplicates them.
- AC-2.3: For a `Post` with status `"ingested"` or `"pending"`, `EnrichAgent` fetches all non-blocked URLs, creates `ExternalLink` rows, and sets `Post.status = "enriched"`.
- AC-2.4: If a URL fetch returns HTTP 200 with HTML content, `ExternalLink.fetch_status = "ok"` and `body_excerpt` is populated (up to 5000 chars).
- AC-2.5: If a URL fetch fails (e.g. HTTP 404, timeout), `ExternalLink.fetch_status = "failed"` and `error_reason` is set; the post itself is still marked `"enriched"` (partial failure is non-fatal).
- AC-2.6: URLs already present in `ExternalLink` with `fetch_status` not `"pending"` are not re-fetched (idempotent).
- AC-2.7: `ExternalLink` rows stuck in `fetch_status = "fetching"` from a previous interrupted run are reset to `"pending"` at the start of each enrich run.
- AC-2.8: `_is_junk_content(text, title)` returns `True` for `None` text, text shorter than 80 chars, and pages that match the YouTube footer pattern; returns `False` for real article text.
- AC-2.9: GitHub repository URLs (`github.com/{user}/{repo}`) are handled by fetching the README from `raw.githubusercontent.com` instead of the HTML page.
- AC-2.10: `lnkd.in` redirect URLs are resolved: the safety-interstitial page is parsed to extract the real destination URL, then fetched recursively (max depth 2).
- AC-2.11: When a `LLMRouter` is provided, fetched links with `body_excerpt` but no `ai_summary` are summarized in batches of 10 via the `batch_client`; `ExternalLink.ai_summary` is set to the response (max 2000 chars).
- AC-2.12: Concurrent link fetches are throttled to `CONCURRENCY = 10`; database writes are serialized through a single semaphore to prevent autoflush races.
- AC-2.13: Playwright is used as a fallback for `403`, `406`, `999`, `500` errors and SSL certificate failures; cookie/login banners are dismissed before content extraction.

### Stage 3 — Classify (`ClassifyAgent`)

**Purpose**: Assign each enriched post to one or more topics from the taxonomy using vLLM batch classification.

**Acceptance Criteria**:

- AC-3.1: All posts with `status in ("enriched", "ingested")` are processed; the batch is split by `settings.batch_size` (default 10).
- AC-3.2: For each post, the LLM response `{"topics": [...], "confidence": 0.9}` is parsed; matched canonical topics create `PostTopic` rows with the correct `confidence_score` and `confidence_tag`.
- AC-3.3: Topics returned by the LLM that don't match a canonical name via `taxonomy.resolve()` are silently skipped (not inserted as unrecognised topics).
- AC-3.4: `confidence_tag` is `"EXTRACTED"` when `confidence_score >= 0.8`, otherwise `"INFERRED"`.
- AC-3.5: If vLLM returns an empty `topics` list, the request is escalated to the Groq client as a single fallback call.
- AC-3.6: After processing, each post's `status` is set to `"classified"`.
- AC-3.7: Posts already at `status in ("ok", "graphed")` that have no `PostTopic` rows are also re-classified (gap fill); their `status` is reset to `"classified"` afterward.
- AC-3.8: If classification of a post raises an exception, the post's `status` is set to `"failed"` (unless it was previously `ok`/`graphed`), and processing continues for remaining posts.

### Stage 4 — Graph Build (`GraphBuildAgent`)

**Purpose**: Create `GraphNode` and `GraphEdge` rows from classified posts.

**Acceptance Criteria**:

- AC-4.1: For each post with `status = "classified"`, a `GraphNode` with `node_type = "post"` is upserted using `node_id = "post_{urn_tail}"`.
- AC-4.2: For each `Topic` in the DB, a `GraphNode` with `node_type = "topic"` is upserted using `node_id = slug(topic.name)`.
- AC-4.3: For each `PostTopic` relationship, a `GraphEdge` is created from the post node to the topic node with `relation = "conceptually_related_to"`, `confidence_score` and `confidence_tag` copied from `PostTopic`.
- AC-4.4: After processing, each post's `status` is set to `"graphed"`.
- AC-4.5: If no posts with `status = "classified"` exist, `StageOutput` is returned with `skipped = 1` and a reason in `meta`.

### Stage 5 — Vault Write (`VaultWriteAgent`)

**Purpose**: Render all graphed posts into Obsidian Markdown notes. Create topic MOC files, author pages, subtopic notes, and an index.

**Acceptance Criteria**:

- AC-5.1: For each post with `status in ("graphed", "ok")`, a Markdown note is written to `obsidian_vault_path/posts/`.
- AC-5.2: Each post note includes: URN, author, subtitle, date, content, topic links, external link summaries, and notable comments.
- AC-5.3: `Post.status` is set to `"ok"` after a note is successfully written.
- AC-5.4: A topic MOC (Map of Content) file is written for each `Topic` to `obsidian_vault_path/topics/`.
- AC-5.5: An author page is written for each distinct `Post.author` to `obsidian_vault_path/authors/`.
- AC-5.6: Stale topic, subtopic, and author files from previous runs are cleared before writing fresh ones.
- AC-5.7: An `index.md` is written to `obsidian_vault_path/` listing all topics with post counts.
- AC-5.8: `_primary_topic(post)` returns the topic with the highest `confidence_score`; ties are broken alphabetically by topic name.
- AC-5.9: Posts with embeddings and a cosine similarity score ≥ 0.85 to other posts are listed as related posts in the note (up to 5).
- AC-5.10: If no posts with `status in ("graphed", "ok")` exist, `StageOutput` is returned with `skipped = 1`.

---

## 5. Subtopic Agent (`SubtopicAgent`)

Runs independently (not in the default `sg run` sequence; called via `sg subtopics`).

**Purpose**: For each topic, generate an LLM title, 1-sentence summary, and fine-grained subtopic label for every post. Merge overlapping subtopics with a Groq consolidation pass.

**Acceptance Criteria**:

- AC-6.1: Posts with `status in ("classified", "graphed", "ok")` are loaded with their topics.
- AC-6.2: Posts are grouped by ALL their topics (not just primary), so every topic gets subtopic coverage.
- AC-6.3: A bootstrap pass processes the first `min(5, N)` posts for each topic with an empty subtopic list to seed the taxonomy.
- AC-6.4: Remaining posts for each topic are processed in batches of 10, with the growing `existing_subtopics` list passed in each prompt.
- AC-6.5: `Post.title` and `Post.summary` are set from the LLM response `{"title": ..., "subtopic": ..., "summary": ...}`.
- AC-6.6: Subtopics are normalised case-insensitively against the existing list; exact case-insensitive matches reuse the existing canonical form.
- AC-6.7: A Groq merge pass runs when a topic has ≥ 4 subtopics; it consolidates overlapping labels by renaming `PostSubtopic` rows in the DB.
- AC-6.8: Posts that already have a `PostSubtopic` row for a given topic are skipped in incremental runs.

---

## 6. Repo (Data Access Layer)

All database operations go through `socialgraph.storage.repo.Repo`. Key acceptance criteria:

- AC-7.1: `get_or_create_post(urn, platform)` returns `(Post, True)` for new posts and `(Post, False)` for existing ones without creating duplicates.
- AC-7.2: `get_or_create_external_link(url)` is race-safe: concurrent tasks racing on the same URL use `INSERT OR IGNORE` and never raise `UniqueConstraint` errors.
- AC-7.3: `upsert_post_topic(post_id, topic_id, score, tag)` updates an existing `PostTopic` row rather than inserting a duplicate.
- AC-7.4: `upsert_graph_node(node_id, node_type, label)` updates `label` on conflict and returns the same node.
- AC-7.5: `bulk_insert_comments(post_id, comments)` skips comments with ranks already present; returns count of newly inserted rows.
- AC-7.6: `rename_subtopic_in_topic(old_name, new_name, topic_id)` updates all matching `PostSubtopic` rows and returns the row count.
- AC-7.7: `get_posts_without_embeddings()` returns only `Post` rows that have no `Embedding` child row.

---

## 7. Enrich Utilities

### URL Handling

- AC-8.1: `should_fetch_url("")` returns `False`.
- AC-8.2: `should_fetch_url("https://linkedin.com/feed")` returns `False`.
- AC-8.3: `should_fetch_url("https://lnkd.in/abc123")` returns `True` (short redirects allowed).
- AC-8.4: `should_fetch_url("ftp://example.com")` returns `False` (non-HTTP schemes rejected).
- AC-8.5: `_extract_urls("See https://example.com, and http://foo.org.")` returns `["https://example.com", "http://foo.org"]` (trailing punctuation stripped).

### Junk Detection

- AC-8.6: `_is_junk_content(None, "Title")` returns `True`.
- AC-8.7: `_is_junk_content("", "Title")` returns `True`.
- AC-8.8: `_is_junk_content("short", "Title")` returns `True` (< 80 chars).
- AC-8.9: `_is_junk_content("javascript is disabled in this browser" + "x"*100, "Twitter")` returns `True`.
- AC-8.10: `_is_junk_content("A"*200, "Normal Article")` returns `False`.

---

## 8. Pipeline Orchestrator

**Acceptance Criteria**:

- AC-9.1: `PipelineOrchestrator.run()` executes stages in the order `["ingest", "enrich", "classify", "graph_build", "vault_write"]`.
- AC-9.2: When `start_from="classify"`, only stages `["classify", "graph_build", "vault_write"]` are executed.
- AC-9.3: When `only_stage="enrich"`, only the `enrich` stage is executed.
- AC-9.4: An invalid `start_from` or `only_stage` value raises `ValueError`.
- AC-9.5: When `dry_run=True`, no agents are called and `PipelineResult.status = "dry_run"`.
- AC-9.6: If a stage produces `failed > 0` and `processed == 0` and `skipped == 0`, the pipeline halts early (no subsequent stages run).
- AC-9.7: A `PipelineRun` row is created in the DB at the start of every run and updated to `status = "ok"` or `"partial"` at completion.
- AC-9.8: `PipelineResult.status = "partial"` when any stage has `failed > 0`; `"ok"` when all stages have `failed == 0`.

---

## 9. Settings (`Settings`)

**Acceptance Criteria**:

- AC-10.1: All settings can be overridden via environment variables with the `SG_` prefix (e.g. `SG_BATCH_SIZE=20`).
- AC-10.2: `vllm_batch_url` defaults to `{vllm_base_url}/v1/chat/completions/batch` when not explicitly set.
- AC-10.3: `Settings.ensure_workspace()` creates `workspace_dir/`, `workspace_dir/logs/`, `obsidian_vault_path/`, `obsidian_vault_path/posts/`, `obsidian_vault_path/topics/`, `obsidian_vault_path/authors/`.
- AC-10.4: `batch_size` must be ≥ 1 and ≤ 50 (validated by pydantic).
- AC-10.5: `schedule_interval_hours` must be > 0.

---

## 10. Taxonomy

**Acceptance Criteria**:

- AC-11.1: `Taxonomy.resolve(raw_name)` returns a canonical topic name for an exact match, an alias match, or a case-insensitive match; returns `None` for completely unrecognised terms.
- AC-11.2: `Taxonomy.as_prompt_list()` returns a formatted string listing all canonical topic names suitable for inclusion in an LLM prompt.

---

## 11. Knowledge / Obsidian

**Acceptance Criteria**:

- AC-12.1: `_slug(name)` converts a topic name to a lowercase, hyphenated, filesystem-safe slug (e.g. `"Machine Learning"` → `"machine-learning"`).
- AC-12.2: `render_post_note(...)` returns a valid Markdown string containing the post URN, author, content, and topic wikilinks.
- AC-12.3: `render_topic_note(...)` returns a Markdown MOC listing all posts grouped by subtopic.
- AC-12.4: `render_author_note(...)` returns a Markdown page listing the author's top topics and recent posts.
- AC-12.5: `VaultWriter.write_post(urn, content)` writes the note to `obsidian_vault_path/posts/post_{urn_tail}.md`.
- AC-12.6: `VaultWriter.clear_topics(platform)` removes all existing topic files for the given platform before a fresh write.

---

## 12. CLI Commands

| Command | Description |
|---------|-------------|
| `sg ingest --json <file>` | Import posts from a JSON file |
| `sg enrich` | Enrich all pending posts (fetch URLs, scrape comments) |
| `sg classify` | Classify posts into topics |
| `sg build-graph` | Build graph nodes and edges |
| `sg vault-write` | Render Obsidian vault |
| `sg run` | Full pipeline (all 5 stages) |
| `sg run --from <stage>` | Resume pipeline from a given stage |
| `sg run --dry-run` | Preview without executing |
| `sg status` | Show counts per pipeline status |
| `sg subtopics` | Run subtopic + title generation |

---

## 13. Test Scope for Automa

Automa should generate tests for the following modules:

| Module | Priority |
|--------|----------|
| `socialgraph/storage/repo.py` | HIGH — all Repo methods |
| `socialgraph/agents/enrich_agent.py` | HIGH — `should_fetch_url`, `_extract_urls`, `_is_junk_content`, `EnrichAgent.run` |
| `socialgraph/agents/classify_agent.py` | HIGH — `ClassifyAgent.run`, `_apply_classification` |
| `socialgraph/agents/ingest_agent.py` | HIGH — `IngestAgent.run` (JSON mode) |
| `socialgraph/agents/graph_build_agent.py` | HIGH — `GraphBuildAgent.run` |
| `socialgraph/agents/vault_write_agent.py` | MEDIUM — `_primary_topic`, `VaultWriteAgent.run` |
| `socialgraph/agents/subtopic_agent.py` | MEDIUM — `SubtopicAgent.run`, `_apply_result`, `_merge_subtopics` |
| `socialgraph/pipeline/orchestrator.py` | MEDIUM — `PipelineOrchestrator.run` with all flag combinations |
| `socialgraph/config/settings.py` | LOW — field validation and `ensure_workspace` |
| `socialgraph/knowledge/obsidian.py` | LOW — `_slug`, `render_post_note`, `render_topic_note` |

Test types:
- **Unit** — pure-function tests with mocked DB and LLM clients (use `pytest-asyncio`)
- **Integration** — in-memory SQLite + real Repo methods (no LLM mocks)

---

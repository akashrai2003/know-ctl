# social-graph — Vision & Architecture

> North-star document. Updated as the system evolves.
> Milestones: [`milestones/`](./milestones/)

---

## What This Is

A **personal knowledge graph** built from your saved LinkedIn posts (and eventually any social/web source). The goal is not a passive archive — it is an **active, queryable second brain** that:

- Understands what you saved and *why* it matters
- Connects ideas across posts, authors, and external articles
- Surfaces trends, gaps, and recommendations proactively
- Is queryable by AI assistants (Claude, Cursor) via MCP
- Continuously updates itself as you save new content

---

## Best-Case Architecture (Full Vision)

```
┌──────────────────────────────────────────────────────────────────────┐
│                         INGESTION LAYER                              │
│                                                                      │
│  LinkedIn (Playwright)   RSS Feeds    Twitter Bookmarks    HN/Reddit │
│        ↓                    ↓               ↓                  ↓    │
│                     IngestAgent (per-source connectors)             │
│                              ↓                                       │
│                         Post (DB, status=ingested)                  │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│                        ENRICHMENT LAYER                              │
│                                                                      │
│  EnrichAgent                                                         │
│  ├── Fetch URLs in post body       → ExternalLink (httpx+trafilatura)│
│  ├── Scrape LinkedIn comments      → Comment (Playwright)            │
│  ├── Fetch URLs in comments        → ExternalLink (context=comment)  │
│  └── vLLM summarize_content        → ExternalLink.body_excerpt (LLM) │
│                                                                      │
│                         Post (status=enriched)                       │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│                       CLASSIFICATION LAYER                           │
│                                                                      │
│  ClassifyAgent                                                       │
│  ├── vLLM batch_chat → PostTopic (primary classification)            │
│  ├── Groq fallback   → PostTopic (single-post retry)                 │
│  └── Groq synthesize_taxonomy → propose new topics (per batch)       │
│                                                                      │
│                         Post (status=classified)                     │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│                         GRAPH LAYER                                  │
│                                                                      │
│  GraphBuildAgent                                                     │
│  ├── GraphNode per post + topic                                      │
│  ├── GraphEdge: post→topic "classified_as"                           │
│  ├── GraphEdge: post→post "elaborates / cites / follow-up" (M2+)    │
│  └── Groq build_graph_structure → semantic edge inference            │
│                                                                      │
│  VectorIndexAgent (M3)                                               │
│  ├── vLLM /v1/embeddings → Post.embedding (sqlite-vec)              │
│  └── vLLM /v1/embeddings → ExternalLink.embedding                   │
│                                                                      │
│  GraphAnalyticsAgent (M4)                                            │
│  ├── NetworkX in-memory traversal                                    │
│  ├── Topic co-occurrence matrix                                      │
│  └── Author influence scores                                         │
│                                                                      │
│                         Post (status=graphed)                        │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│                         OUTPUT LAYER                                 │
│                                                                      │
│  VaultWriteAgent → Obsidian .md notes (posts / topics / authors)    │
│  DigestAgent (M9) → weekly summary .md via Groq synthesize_insights  │
│  WebAPI (M7) → FastAPI + HTMX browser UI                            │
│  MCPServer (M5) → stdio + HTTP MCP for Claude Desktop / Cursor      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## LLM Model Assignment

| Task | Model | Rationale |
|------|-------|-----------|
| `classify_post_topics` (batch) | vLLM Qwen3.5-9B | High volume, simple structured output |
| `extract_raw_topics` (batch) | vLLM Qwen3.5-9B | Pre-classification candidate extraction |
| `summarize_content` (batch) | vLLM Qwen3.5-9B | URL article summarization |
| `parse_link_metadata` (batch) | vLLM Qwen3.5-9B | Structured extraction from HTML |
| `classify_comment` (single) | vLLM Qwen3.5-9B | Per-comment topic/sentiment |
| `synthesize_taxonomy` | Groq llama-3.3-70b | Judgment: propose new canonical topics |
| `build_graph_structure` | Groq llama-3.3-70b | Reason about semantic edges between posts |
| `expand_taxonomy` | Groq llama-3.3-70b | Verify + approve alias expansions |
| `synthesize_insights` | Groq llama-3.3-70b | Weekly digest, gap analysis, trend narrative |

Fallback chain: Groq `llama-3.3-70b-versatile` → `meta-llama/llama-4-scout-17b-16e-instruct` → `qwen/qwen3-32b`

---

## Data Model Overview

```
Post ──< PostTopic >── Topic
 │                      │
 │                      └─ aliases: list[str]
 │
 ├──< Comment
 │        └── (url extraction) → ExternalLink
 │
 ├──< PostExternalLink >── ExternalLink
 │        context: "body" | "comment"
 │
 ├── GraphNode (id=urn)
 │       └──< GraphEdge >── GraphNode
 │              type: classified_as | elaborates | cites | follow_up
 │
 └── Embedding (M3, sqlite-vec)
```

---

## MCP Surface (M5 Target)

Tools exposed to Claude/Cursor:

| Tool | Args | Returns |
|------|------|---------|
| `search_posts` | `query, topic?, author?, limit?` | Ranked post list (hybrid BM25 + semantic) |
| `get_topic_summary` | `name` | Description, post count, top authors, top links |
| `get_author_profile` | `name` | Posts, dominant topics, key external links |
| `find_similar` | `urn` | Nearest-neighbor posts by embedding |
| `traverse_graph` | `topic, depth?` | All posts reachable within N hops |
| `get_weekly_digest` | `days?` | Themed summary of recently saved posts |
| `list_topics` | — | All canonical topics with counts |
| `get_timeline` | `topic?, author?` | Posts sorted by `date_raw` |

---

## Milestones Summary

| # | Name | Key Deliverable | Status |
|---|------|-----------------|--------|
| M0 | Foundation | Ingest → classify → vault-write, 1508 posts | ✅ Done |
| M1 | Deep Enrichment | Link fetch + LLM summarize + comment scraping | 🔲 |
| M2 | Full LLM Router | Big model for taxonomy synthesis + graph edges | 🔲 |
| M3 | Vector Search | Semantic search, `sg search`, similar posts | 🔲 |
| M4 | Graph Intelligence | NetworkX traversal, co-occurrence, trends | 🔲 |
| M5 | MCP Server | Claude/Cursor can query the knowledge graph | 🔲 |
| M6 | Live Ingestion | Scheduler, incremental updates, auto-ingest | 🔲 |
| M7 | Web UI | FastAPI + browser UI, graph visualization | 🔲 |
| M8 | Multi-Source | RSS, Twitter bookmarks, HN, Reddit | 🔲 |
| M9 | AI Analyst | Digest, gap analysis, reading queue | 🔲 |
| M10 | Production Grade | Docker, caching, metrics, backup/restore | 🔲 |

Detailed action points: [`milestones/`](./milestones/)

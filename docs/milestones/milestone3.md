# Milestone 3 — Vector Embeddings & Semantic Search

> Parent plan: [`../vision.md`](../vision.md)
> Predecessor: [`milestone2.md`](./milestone2.md)
> Owner: 1 engineer · Timebox: ~4 days · Status: 🔲 Not started

---

## 1. Goal

Make the knowledge graph *semantically searchable*. Embed every post and linked article using a local embedding model served through vLLM, store vectors in SQLite via `sqlite-vec` (no new service dependency), and expose `sg search` and `sg similar` CLI commands. Vault notes get a `related_posts:` frontmatter section populated from nearest-neighbor embeddings.

This replaces brittle keyword search with meaning-based retrieval — the foundation for the MCP server in M5.

---

## 2. Exit Criteria

- [ ] `sqlite-vec` installed and loadable (`python3 -c "import sqlite_vec"`).
- [ ] New `Embedding` table: `(id, entity_type, entity_id, model, vector BLOB, created_at)`.
- [ ] `sg embed` command: embeds all posts + external links via vLLM `/v1/embeddings` endpoint; stores in `Embedding` table.
- [ ] Re-running `sg embed` is idempotent: skips already-embedded entities unless `--force`.
- [ ] `sg search "query string"` → top-10 posts by cosine similarity, with topic tags and author shown.
- [ ] `sg search "query" --topic "Machine Learning"` → filtered to topic before re-ranking.
- [ ] `sg similar <urn>` → top-5 nearest-neighbor posts by embedding.
- [ ] Vault notes re-written with `related_posts:` frontmatter (top-3 similar posts by embedding).
- [ ] `sg status` shows embedding coverage: `N posts embedded / 1508`.
- [ ] `ruff check` passes; unit tests for cosine similarity helper pass.

---

## 3. Action Points

### Day 1 — Storage & Embedding Model Setup

- **AP-3.1** Add `sqlite-vec` to `pyproject.toml` dependencies.
- **AP-3.2** New Alembic migration: `Embedding` table — `id, entity_type (post|link), entity_id (int), model (str), vector (BLOB), created_at`. Unique constraint on `(entity_type, entity_id, model)`.
- **AP-3.3** `socialgraph/storage/repo.py`: add `upsert_embedding(entity_type, entity_id, model, vector: list[float])` and `get_embedding(entity_type, entity_id, model)`.
- **AP-3.4** `socialgraph/indexer/vector_store.py`: thin wrapper that loads `sqlite-vec` extension on connection, exposes `cosine_search(query_vec, entity_type, top_k, topic_filter?)` → `list[(entity_id, score)]`.
- **AP-3.5** Verify vLLM exposes `/v1/embeddings` endpoint; test with `curl` using a short string.

### Day 2 — VectorIndexAgent

- **AP-3.6** `socialgraph/agents/embed_agent.py`: `EmbedAgent.run(ctx)`.
  - Fetch all posts not yet embedded (`Embedding` table join).
  - Build embedding text per post: `f"{post.author}: {post.content[:1000]}"`. Truncate to model max tokens.
  - Call vLLM `/v1/embeddings` in batches of 64 (httpx, same pattern as batch_chat).
  - Store each vector via `repo.upsert_embedding("post", post.id, model, vector)`.
  - Repeat for `ExternalLink` rows with `fetch_status="ok"`: embed `f"{title}. {body_excerpt}"`.
- **AP-3.7** Add `embed` stage to pipeline orchestrator and `sg embed` CLI command.
- **AP-3.8** `SG_EMBEDDING_MODEL` env var in `settings.py` (default: same vLLM instance, model `nomic-embed-text` or the loaded model's embedding support).

### Day 3 — Search CLI Commands

- **AP-3.9** `socialgraph/search/searcher.py`: `Searcher` class.
  - `search(query, topic_filter?, top_k=10)`: embed query via vLLM, cosine search in sqlite-vec, optionally filter by topic via join.
  - `similar(post_id, top_k=5)`: fetch post embedding, cosine search excluding self.
  - Returns `list[SearchResult(urn, author, content_preview, topics, score)]`.
- **AP-3.10** `sg search "<query>" [--topic TOPIC] [--limit N]` CLI command: calls `Searcher.search()`, prints table of results.
- **AP-3.11** `sg similar <urn>` CLI command: calls `Searcher.similar()`, prints results.
- **AP-3.12** Unit tests: mock embedding responses, assert result ordering by score.

### Day 4 — Vault Integration + E2E

- **AP-3.13** `VaultWriteAgent`: after writing all notes, for each post fetch top-3 similar posts via `Searcher.similar()`, add to `related_posts:` frontmatter.
- **AP-3.14** `render_post_note()`: add `related_posts: ["[[urn1]]", "[[urn2]]", "[[urn3]]"]` frontmatter field.
- **AP-3.15** Run full pipeline: `sg enrich && sg classify && sg embed && sg build-graph && sg vault-write`.
- **AP-3.16** Verify: `sg search "RLHF reward modeling"` returns relevant posts; Obsidian notes have `related_posts` populated with wiki-links.

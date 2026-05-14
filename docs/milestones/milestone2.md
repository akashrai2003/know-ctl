# Milestone 2 — Full LLM Router Activation

> Parent plan: [`../vision.md`](../vision.md)
> Predecessor: [`milestone1.md`](./milestone1.md)
> Owner: 1 engineer · Timebox: ~4 days · Status: 🔲 Not started

---

## 1. Goal

Activate the four Groq tasks that are wired in `router.py` but never called: `synthesize_taxonomy`, `build_graph_structure`, `expand_taxonomy`, and `synthesize_insights` (preview). Also activate vLLM's `extract_raw_topics` pre-classification pass and `classify_comment` for per-comment topic tagging.

By the end of M2, the big model earns its keep: it auto-proposes taxonomy updates after each ingest batch, infers semantic edges between posts (not just "classified_as"), and comments are tagged with topics just like posts.

---

## 2. Exit Criteria

- [ ] `sg classify --update-taxonomy` runs `synthesize_taxonomy` via Groq at the end of each classification batch: proposes candidate new topics (JSON) if the model detects uncovered themes.
- [ ] Proposed topics are written to `.socialgraph/taxonomy_proposals.json` and shown to the user via CLI for approval (`sg taxonomy review`).
- [ ] `sg build-graph --semantic-edges` calls `build_graph_structure` via Groq on batches of 20 posts; produces `GraphEdge` rows with `edge_type` ∈ `{elaborates, cites, contradicts, follow_up}` in addition to `classified_as`.
- [ ] `extract_raw_topics` (vLLM batch) runs as a pre-pass before classification: extracts raw topic strings from each post, stored in `Post.raw_topics_json`. Classification uses these as additional context.
- [ ] `classify_comment` (vLLM single) tags each `Comment` with a topic from the canonical taxonomy. `Comment.topic_id` FK populated.
- [ ] `sg status` shows edge type breakdown: `classified_as N, elaborates N, cites N`.
- [ ] Vault notes updated: `related_posts:` frontmatter lists posts linked via semantic edges.
- [ ] `ruff check` passes; existing tests pass.

---

## 3. Action Points

### Day 1 — Taxonomy Synthesis

- **AP-2.1** Add `synthesize_taxonomy` prompt to `socialgraph/llm/prompts.py`: system = taxonomy curator persona; user = list of raw topics extracted from current batch + current canonical taxonomy. Ask model for JSON: `{"new_topics": [{"name": ..., "description": ..., "aliases": [...]}], "alias_additions": {"ExistingTopic": ["new_alias"]}}`.
- **AP-2.2** `ClassifyAgent.run()`: after classification batch completes, if `update_taxonomy=True`, call Groq `synthesize_taxonomy`. Write proposals to `.socialgraph/taxonomy_proposals.json`.
- **AP-2.3** `sg taxonomy review` CLI command: display proposals, prompt `[a]ccept / [s]kip / [e]dit` per proposed topic. Accepted topics are merged into `topic_taxonomy.json` and DB.
- **AP-2.4** `sg classify` gains `--update-taxonomy / --no-update-taxonomy` flag (default: off).

### Day 2 — Semantic Graph Edges

- **AP-2.5** New Alembic migration: add `edge_type: str` column to `GraphEdge` table (default `"classified_as"`). Backfill existing rows.
- **AP-2.6** `build_graph_structure` prompt: given 20 posts (urn + content snippet + topics), return JSON: `[{"from_urn": ..., "to_urn": ..., "edge_type": "elaborates|cites|contradicts|follow_up", "rationale": ...}]`. Only emit edges with high confidence.
- **AP-2.7** `GraphBuildAgent`: add `--semantic-edges` flag. When set, batch posts in groups of 20, call Groq, insert `GraphEdge` rows for returned pairs. Skip if `from_urn == to_urn`.
- **AP-2.8** Deduplication: `GraphEdge` gets unique constraint on `(from_node_id, to_node_id, edge_type)`.

### Day 3 — Pre-Classification Topic Extraction + Comment Classification

- **AP-2.9** `extract_raw_topics` prompt: given post content, return JSON `{"topics": ["topic string 1", ...]}` — raw strings, not canonical. Max 5 per post.
- **AP-2.10** Add `raw_topics_json` text column to `Post` model + migration.
- **AP-2.11** `ClassifyAgent.run()`: before classification pass, run `extract_raw_topics` via vLLM batch on all posts. Store in `Post.raw_topics_json`. Inject into classification prompt as "hint topics".
- **AP-2.12** Add `topic_id` nullable FK column to `Comment` model + migration.
- **AP-2.13** `classify_comment` prompt: given comment text + canonical topic list, return `{"topic": "TopicName" | null}`.
- **AP-2.14** `ClassifyAgent` (or new `CommentClassifyAgent`): after post classification, classify all comments via vLLM `single_chat`. Batch as many as possible per request using grouped messages.

### Day 4 — Vault + E2E

- **AP-2.15** `render_post_note()`: add `related_posts:` frontmatter section listing post URNs connected via semantic edges (elaborates, cites, follow_up).
- **AP-2.16** `render_topic_note()`: add `related_topics:` section derived from co-occurring topics on shared posts (top 5 by frequency).
- **AP-2.17** Run full pipeline: `sg enrich && sg classify --update-taxonomy && sg build-graph --semantic-edges && sg vault-write`.
- **AP-2.18** Verify: check `GraphEdge` table has rows with non-`classified_as` edge types; check vault notes have `related_posts` populated.

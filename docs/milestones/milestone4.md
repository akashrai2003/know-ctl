# Milestone 4 — Graph Intelligence & Analytics

> Parent plan: [`../vision.md`](../vision.md)
> Predecessor: [`milestone3.md`](./milestone3.md)
> Owner: 1 engineer · Timebox: ~4 days · Status: 🔲 Not started

---

## 1. Goal

Load the knowledge graph into memory (NetworkX) and make it analytically useful: traverse by topic, compute co-occurrence, rank authors by influence, and surface temporal trends. The graph becomes queryable at a structural level — not just "find similar posts" but "which authors bridge the most topics?" and "what was the fastest-growing topic in Q4 2024?".

---

## 2. Exit Criteria

- [ ] `socialgraph/graph/analytics.py`: `GraphAnalytics` class loads all `GraphNode` + `GraphEdge` rows into a NetworkX directed graph.
- [ ] `sg graph traverse --topic "Machine Learning" --depth 2` → list of posts reachable within N hops from the topic node.
- [ ] `sg graph stats` → prints: node count, edge count, top-10 posts by degree, top-10 topics by post count, top-5 authors by post count.
- [ ] `sg graph co-occurrence` → top-20 topic pairs that most frequently appear together on the same post; output as markdown table.
- [ ] `sg graph authors` → per-author: post count, dominant topics (top 3), most linked external domains.
- [ ] `sg graph timeline [--topic TOPIC]` → post count per month aggregated from `date_raw`; output as markdown table suitable for pasting into Obsidian.
- [ ] Vault updated: each topic MOC file gains a `top_authors:` section and a `monthly_trend:` mini-table.
- [ ] `ruff check` passes; unit tests for graph loading and traversal pass.

---

## 3. Action Points

### Day 1 — GraphAnalytics Core

- **AP-4.1** Add `networkx` to `pyproject.toml` dependencies.
- **AP-4.2** `socialgraph/graph/analytics.py`: `GraphAnalytics` class.
  - `load(db_session)`: async — fetch all `GraphNode` and `GraphEdge` rows, build `nx.DiGraph`.
  - Node attributes: `node_type` (post | topic), `author`, `date_raw`, `topics`.
  - Edge attributes: `edge_type`, `weight` (default 1.0).
- **AP-4.3** `traverse(start_node_id, depth)` → `list[GraphNode]` reachable within depth hops.
- **AP-4.4** `degree_centrality()` → top-N posts by in-degree (most cited / related).
- **AP-4.5** Unit tests: small fixture graph (10 nodes, 15 edges), assert traversal returns correct subgraph.

### Day 2 — Co-occurrence & Author Profiles

- **AP-4.6** `co_occurrence_matrix()` → `dict[(topic_a, topic_b), count]` — iterate posts, for each post generate all topic pairs and increment counter.
- **AP-4.7** `author_profiles()` → `dict[author_name, AuthorProfile(post_count, top_topics, top_domains)]`.
  - `top_domains`: extract domain from all `ExternalLink` URLs associated with that author's posts.
- **AP-4.8** `AuthorProfile` Pydantic model: `author, post_count, top_topics: list[str], top_domains: list[str]`.
- **AP-4.9** Unit tests for co-occurrence and author profile aggregation.

### Day 3 — Temporal Analysis + CLI Commands

- **AP-4.10** `temporal_trend(topic?)` → `dict[month_str, int]` — parse `date_raw` (best-effort; handle missing/malformed). Month key format: `"YYYY-MM"`.
- **AP-4.11** `sg graph traverse --topic TOPIC [--depth N]` CLI command.
- **AP-4.12** `sg graph stats` CLI command: tabulated output.
- **AP-4.13** `sg graph co-occurrence [--top N]` CLI command: markdown table output.
- **AP-4.14** `sg graph authors [--top N]` CLI command.
- **AP-4.15** `sg graph timeline [--topic TOPIC]` CLI command: markdown table.

### Day 4 — Vault Integration

- **AP-4.16** `render_topic_note()` updated: add `top_authors:` frontmatter (top-5 by post count in that topic) and `monthly_trend:` markdown table (last 12 months).
- **AP-4.17** New vault section `authors/`: one `.md` file per author with post list, dominant topics, top linked domains.
- **AP-4.18** `VaultWriteAgent`: write author profiles to `authors/` directory.
- **AP-4.19** Run full pipeline including vault-write; spot-check 3 topic MOC files for trend tables and author sections.

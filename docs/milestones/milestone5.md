# Milestone 5 — MCP Server

> Parent plan: [`../vision.md`](../vision.md)
> Predecessor: [`milestone4.md`](./milestone4.md)
> Owner: 1 engineer · Timebox: ~3 days · Status: 🔲 Not started

---

## 1. Goal

Expose the knowledge graph as a **Model Context Protocol server** so Claude Desktop, Cursor, and any MCP-compatible AI assistant can query your saved posts, search by topic, traverse the graph, and get weekly digests — all in natural language backed by real data.

The MCP server runs as a long-lived process (`sg mcp serve`) and supports both stdio (Claude Desktop) and HTTP (Cursor/web).

---

## 2. Exit Criteria

- [ ] `fastmcp` (or equivalent MCP library) added to dependencies.
- [ ] `sg mcp serve [--port 8765] [--transport stdio|http|both]` starts the MCP server.
- [ ] All 8 tools from the vision are implemented and callable:
  - `search_posts(query, topic?, author?, limit?)` — hybrid: keyword filter + semantic (M3 embeddings).
  - `get_topic_summary(name)` — description, post count, top authors, top linked articles.
  - `get_author_profile(name)` — all posts, dominant topics, key external links.
  - `find_similar(urn)` — top-5 nearest neighbors from embedding index.
  - `traverse_graph(topic, depth?)` — posts reachable via graph edges (M4 analytics).
  - `get_weekly_digest(days?)` — posts saved in last N days, summarized by topic group.
  - `list_topics()` — all canonical topics with post counts.
  - `get_timeline(topic?, author?)` — posts sorted by `date_raw`.
- [ ] Claude Desktop config (`claude_desktop_config.json`) snippet documented in README.
- [ ] Cursor MCP config (`mcp.json`) snippet documented in README.
- [ ] All tools return structured JSON with consistent schema (post objects include `urn, author, content_preview, topics, source_url, date_raw`).
- [ ] MCP server logs every tool call via structlog (`mcp.tool_called`, `mcp.tool_response` with latency).
- [ ] `ruff check` passes; unit tests for each tool handler (mocked DB) pass.

---

## 3. Action Points

### Day 1 — MCP Infrastructure

- **AP-5.1** Add `fastmcp>=2.0` to `pyproject.toml`.
- **AP-5.2** `socialgraph/mcp/server.py`: `MCPServer` class wrapping `fastmcp.FastMCP`.
  - `__init__(settings, db_factory, searcher, analytics)`: inject dependencies.
  - `register_tools()`: register all 8 tool handlers.
- **AP-5.3** `sg mcp serve` CLI command: init settings, build DB session factory, init `Searcher` (M3) and `GraphAnalytics` (M4), start `MCPServer`.
- **AP-5.4** `SG_MCP_PORT` env var (default: 8765), `SG_MCP_TRANSPORT` (default: `both`).
- **AP-5.5** Structlog middleware: wrap every tool call with `mcp.tool_called` (tool name, args preview) and `mcp.tool_response` (latency_ms, result_count).

### Day 2 — Tool Implementations

- **AP-5.6** `search_posts`: call `Searcher.search(query, topic_filter, top_k=limit or 10)`. Return list of post dicts.
- **AP-5.7** `get_topic_summary`: DB query for topic + count(PostTopic) + top-5 authors by post count in topic + top-3 external links (by `ExternalLink` fetch_status=ok).
- **AP-5.8** `get_author_profile`: DB query all posts for author + aggregate topics + external link domains.
- **AP-5.9** `find_similar`: call `Searcher.similar(urn_to_post_id(urn), top_k=5)`.
- **AP-5.10** `traverse_graph`: call `GraphAnalytics.traverse(topic_node_id, depth)`, return post list.
- **AP-5.11** `list_topics`: return all `Topic` rows with `post_count` from `COUNT(PostTopic)`.
- **AP-5.12** `get_timeline`: DB query posts filtered by topic/author, sorted by `date_raw` DESC.

### Day 3 — Digest Tool + Docs + E2E

- **AP-5.13** `get_weekly_digest`: fetch posts where `created_at >= now - days`. Group by topic. For each group, call Groq `synthesize_insights` with post content snippets → 2-sentence theme summary per topic.
- **AP-5.14** Digest caches result in `.socialgraph/digest_cache.json` (keyed by date + period) — avoid re-calling Groq for the same digest window.
- **AP-5.15** Document Claude Desktop config in `README.md`:
  ```json
  {"mcpServers": {"social-graph": {"command": "sg", "args": ["mcp", "serve", "--transport", "stdio"]}}}
  ```
- **AP-5.16** Document Cursor `mcp.json` config (HTTP transport, `http://localhost:8765`).
- **AP-5.17** Integration test: start server, call each tool via HTTP, assert non-empty JSON response.

# Milestone 7 — Web UI & REST API

> Parent plan: [`../vision.md`](../vision.md)
> Predecessor: [`milestone6.md`](./milestone6.md)
> Owner: 1 engineer · Timebox: ~5 days · Status: 🔲 Not started

---

## 1. Goal

Expose the knowledge graph through a browser UI and REST API so the knowledge base is browsable without Obsidian, searchable via a text box, and visualizable as an interactive graph. The existing `backend/` skeleton gets fleshed out with real endpoints backed by the M3 searcher and M4 analytics.

---

## 2. Exit Criteria

- [ ] `sg web [--port 8080]` starts the FastAPI server + serves the frontend.
- [ ] REST API endpoints (JSON):
  - `GET /api/topics` — list all topics with post counts.
  - `GET /api/topics/{name}` — topic detail: description, posts, top authors, trend data.
  - `GET /api/posts?topic=&author=&q=&limit=` — filtered + semantically ranked post list.
  - `GET /api/posts/{urn}` — post detail: content, topics, external links, comments, similar posts.
  - `GET /api/authors` — author list with post counts.
  - `GET /api/authors/{name}` — author profile: posts, dominant topics.
  - `GET /api/search?q=&topic=` — semantic search endpoint (M3).
  - `GET /api/graph` — graph data in D3-compatible JSON `{nodes: [...], links: [...]}`.
  - `GET /api/stats` — summary statistics.
- [ ] Frontend (HTMX + minimal CSS, no build step required):
  - Home: topic grid with post counts, search bar.
  - Topic page: post list + monthly trend mini-chart (SVG).
  - Post page: full content, external link summaries, related posts (M3), comments.
  - Author page: post timeline, topic breakdown.
  - Graph page: D3.js force-directed graph of topics ↔ posts (topic nodes larger, colored by cluster).
- [ ] Search bar on every page: `GET /api/search` → results page with ranked posts.
- [ ] `ruff check` passes; API endpoints have basic unit tests (mocked DB).

---

## 3. Action Points

### Day 1 — API Foundation (flesh out `backend/`)

- **AP-7.1** `backend/main.py`: mount FastAPI app, add CORS, serve static frontend files from `backend/static/`.
- **AP-7.2** `backend/deps.py`: dependency-inject DB session, `Searcher`, `GraphAnalytics` instances.
- **AP-7.3** `backend/schemas.py`: Pydantic response models — `TopicOut`, `PostOut`, `PostDetailOut`, `AuthorOut`, `GraphData`, `SearchResult`.
- **AP-7.4** `backend/service.py`: service layer wrapping DB queries, `Searcher`, `GraphAnalytics`.
- **AP-7.5** Implement `GET /api/topics` and `GET /api/topics/{name}`.
- **AP-7.6** Implement `GET /api/posts` (with filtering) and `GET /api/posts/{urn}`.

### Day 2 — Remaining API Endpoints

- **AP-7.7** Implement `GET /api/authors` and `GET /api/authors/{name}`.
- **AP-7.8** Implement `GET /api/search?q=&topic=`: call `Searcher.search()`, return `list[SearchResult]`.
- **AP-7.9** Implement `GET /api/graph`: load `GraphAnalytics`, return D3-compatible JSON. Filter to topic nodes + top-200 most-connected post nodes to keep payload manageable.
- **AP-7.10** Implement `GET /api/stats`: total posts, topics, authors, external links, embeddings, last pipeline run.
- **AP-7.11** Add rate limiting (slowapi) on search endpoint: 30 req/min.

### Day 3 — Frontend: Home + Topic + Post Pages

- **AP-7.12** `backend/static/index.html`: HTMX-driven home page — topic grid (fetches `/api/topics`), search bar at top.
- **AP-7.13** Topic page (`/topics/{name}`): post list, top authors list, monthly trend as SVG bar chart (inline, generated server-side via `/api/topics/{name}`).
- **AP-7.14** Post page (`/posts/{urn}`): full content, topics as badges, external link cards (title + summary), related posts section, comments section.

### Day 4 — Frontend: Author + Graph Pages

- **AP-7.15** Author page (`/authors/{name}`): post count, dominant topics, chronological post list.
- **AP-7.16** Graph page (`/graph`): loads `/api/graph` JSON, renders D3.js force-directed graph. Topic nodes colored by cluster (19 colors), post nodes grey. Click a node → navigate to topic/post page.
- **AP-7.17** Navigation: top nav bar with links to Home, Graph, Topics, Authors, Search.

### Day 5 — `sg web` Command + Polish

- **AP-7.18** `sg web [--port PORT] [--host HOST]` CLI command: starts uvicorn, opens browser.
- **AP-7.19** `SG_WEB_PORT` env var (default: 8080).
- **AP-7.20** API unit tests: 5 endpoints, mocked DB, assert status 200 + schema.
- **AP-7.21** E2E smoke: `sg web &`, `curl /api/stats`, assert `total_posts > 0`.

# Social Graph

[![CI](https://github.com/your-username/social-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/your-username/social-graph/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/downloads/)

Transform LinkedIn saved posts into a navigable Obsidian knowledge graph.

Social Graph automates fetching saved posts, downloading linked external articles, extracting comments, generating embeddings, identifying topics, detecting communities, and building a local Markdown-based personal knowledge graph complete with link-backs and monthly timeline files. It also includes a local FastAPI/Uvicorn web dashboard and an MCP (Model Context Protocol) server integration.

## Key Features

1. **Ingest** — Import saved posts from exported JSON files or scrape live via Playwright.
2. **Comment Scraping** — Retrieve thread comments directly using the Voyager API.
3. **URL Enrichment** — Automatically crawl external web page links referenced in posts and comments.
4. **LLM Routing** — Efficiently distribute tasks: light classification to local/hosted vLLM batch models, complex synthesis and community graph layout to Groq.
5. **Local Embeddings** — Generate vector embeddings locally for semantic similarity matching.
6. **Obsidian Vault Writer** — Render clean notes in Obsidian with YAML frontmatter, backlinks, and topic MOCs.
7. **Web Dashboard** — Visualize your knowledge base as a force-directed graph, browse posts by author/topic, and run semantic queries.
8. **MCP Server** — Query your social graph directly from LLM-powered tools (like Claude Desktop).

---

## Quick Start

### Prerequisites
- Python >= 3.10
- Node (optional, for web UI assets if modified)

### Installation
```bash
# Clone the repository
git clone https://github.com/akashrai2003/social-graph.git
cd social-graph

# Set up virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
make install-dev

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials (Groq key, base URLs, etc.)
```

### Initialize Workspace
```bash
# Run migration to setup DB tables and folders
sg init
```

### Build Taxonomy & Run
```bash
# Build the initial topic taxonomy from posts
make bootstrap-taxonomy

# Run the complete incremental pipeline
sg run
```

---

## Architecture

```
linkedin_saved_posts.json
         │
         ▼
     [ingest]  ──── SQLite (.socialgraph/socialgraph.db)
         │
         ▼
     [enrich]  ──── trafilatura + httpx → ExternalLink rows
         │
         ▼
   [classify]  ──── vLLM (Qwen3.5) batch → PostTopic rows
         │
         ▼
 [graph_build] ──── Groq (Llama-3.3-70b) → graphifyy Leiden
         │
         ▼
 [vault_write] ──── Obsidian .md files → vault/
```

### LLM & Embedding Setup
- **vLLM (self-hosted)**: Handles high-throughput batch extraction and classification tasks (e.g., `Qwen/Qwen3.5-9B-FP8`).
- **Groq API**: High-speed execution of heavier reasoning tasks (e.g., `llama-3.3-70b-versatile`).
- **Local Embeddings**: Generates embeddings locally using `sentence-transformers` (defaults to `Qwen/Qwen3-Embedding-0.6B` on CPU/CUDA).

---

## CLI Commands Reference

Social Graph comes with a CLI (`sg`) for granularity over the pipeline:

```bash
# Workspace & Pipeline Status
sg init                          # Initialize workspace and DB tables
sg status                        # Show current status of posts and scheduler

# Running the pipeline
sg run                           # Run full pipeline end-to-end
sg run --from classify           # Resume pipeline starting from the classify stage
sg run --stage enrich            # Run ONLY the enrich stage

# Granular Pipeline Stages
sg ingest --json <file>          # Ingest posts from a JSON export
sg scrape                        # Open browser (Playwright) to pull saved posts live
sg comments                      # Scrape LinkedIn comments for ingested posts
sg enrich                        # Enrich pending posts (fetch URLs)
sg comment-enrich                # Fetch and summarize links in comments
sg classify                      # Classify posts into topics
sg embed                         # Generate vector embeddings
sg subtopic                      # Detect subtopics within categories
sg semantic-edges                # Build edges between posts by cosine similarity
sg build-graph                   # Build the knowledge graph nodes/edges
sg vault-write                   # Write notes to the Obsidian vault directory

# Semantic Search
sg search "vector databases"     # Semantic search over your posts
sg similar "urn:li:activity:..." # Find semantically similar posts

# Graph Analytics
sg graph stats                   # View topic and author distributions
sg graph co-occurrence           # Show top topic co-occurrences
sg graph timeline                # Show monthly post counts filtered by author/topic

# Scheduler (Background Daemon)
sg schedule start                # Start background daemon (pipeline runs every 6h)
sg schedule stop                 # Stop background scheduler
sg schedule status               # Show status of background daemon

# Web UI & Integrations
sg web                           # Start local dashboard (http://localhost:8080)
sg mcp-serve                     # Start Model Context Protocol server (stdio or sse)
```

---

## Configuration

Custom configurations can be supplied in your `.env` file:
```ini
# LLM Providers
SG_VLLM_BASE_URL=http://localhost:8000
SG_GROQ_API_KEY=gsk_...

# Browser scraping
SG_LINKEDIN_EMAIL=user@example.com
SG_LINKEDIN_PASSWORD=your_password

# Pipeline tweaks
SG_MAX_COMMENTS=5
SG_SCHEDULE_INTERVAL_HOURS=6.0
SG_WEB_PORT=8080
```

---

## Project Structure

```
socialgraph/            # Main Python source package
  ├── agents/           # Pipeline stage agents (Ingest, Classify, Enrich, etc.)
  ├── cli/              # Modular typer CLI commands
  ├── config/           # Application configuration models
  ├── connectors/       # API and browser scrape integrations
  ├── knowledge/        # Obsidian rendering, search, and graph algorithms
  ├── llm/              # OpenAI/Groq router & client classes
  ├── storage/          # SQLAlchemy schemas, migrations, repository layer
  └── web/              # FastAPI application endpoints & assets
tests/                  # Complete test suite (unit, integration, e2e)
vault/                  # Default Obsidian vault output directory (git-ignored)
.socialgraph/           # Default SQLite DB and application cache (git-ignored)
```

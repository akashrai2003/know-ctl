# Social Graph

[![CI](https://github.com/akashrai2003/social-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/akashrai2003/social-graph/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/downloads/)

Transform LinkedIn saved posts into a navigable Obsidian knowledge graph.

Social Graph automates fetching saved posts, downloading linked external articles, extracting comments, generating embeddings, identifying topics, detecting communities, and building a local Markdown-based personal knowledge graph complete with link-backs and monthly timeline files. It also includes a local FastAPI/Uvicorn **web dashboard** with a built-in setup wizard so you can configure everything from the browser — no `.env` file needed.

## Key Features

1. **Ingest** — Import saved posts from exported JSON files or scrape live via Playwright.
2. **Comment Scraping** — Retrieve thread comments directly using the Voyager API.
3. **URL Enrichment** — Automatically crawl external web page links referenced in posts and comments.
4. **LLM Routing** — Hybrid mode: light classification via any OpenAI-compatible local server (vLLM, llama.cpp, Ollama), complex synthesis via Groq. Auto-detects `/batch` endpoint support.
5. **Local Embeddings** — Generate vector embeddings locally for semantic similarity matching.
6. **Obsidian Vault Writer** — Render clean notes in Obsidian with YAML frontmatter, backlinks, and topic MOCs.
7. **Web Dashboard** — Configure keys, upload data, run pipelines, and visualize your graph — all from the browser.
8. **MCP Server** — Query your social graph directly from LLM-powered tools (like Claude Desktop).

---

## ⚡ Quick Start (Recommended — Web UI)

No `.env` required. Configure everything from the browser.

### 1. Install

```bash
git clone https://github.com/akashrai2003/social-graph.git
cd social-graph

# Install dependencies (Python 3.10+)
pip install -e .

# Or with dev tools
pip install -e ".[dev]"
```

### 2. Initialize & Launch

```bash
# Create workspace directories and database
sg init

# Start the web dashboard
sg web
```

Open **http://localhost:8080** in your browser.

### 3. Setup Wizard

The app will guide you through a 5-step onboarding wizard on first launch:

1. **Welcome** — Overview of what Social Graph does
2. **Groq API Key** — Get a free key at [console.groq.com](https://console.groq.com) (takes 30 seconds)
3. **Local Model** *(optional)* — Connect vLLM, llama.cpp, Ollama, or any OpenAI-compatible server
4. **LinkedIn** *(optional)* — Email/password or session cookie for live scraping
5. **Done** — Upload your LinkedIn data or click "Run Pipeline"

### 4. Upload LinkedIn Data

In the **Settings** page, upload your `linkedin_saved_posts.json` export:

> LinkedIn → Me → Settings & Privacy → Data Privacy → Get a copy of your data → select "Saved items"

### 5. Run

Click **⚡ Run Pipeline** in the Pipeline page and watch the real-time log stream.

---

## Alternative: CLI Setup (`.env` file)

If you prefer the traditional approach, copy `.env.example` and fill in your keys:

```bash
cp .env.example .env
# Edit .env with your credentials
sg init
sg run
```

> **Note:** Settings configured via the web UI take precedence over `.env` values.

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
   [classify]  ──── Local model (vLLM/llama.cpp/Ollama) batch → PostTopic rows
         │                    ↕ auto-fallback to concurrent calls if no /batch
         ▼
 [graph_build] ──── Groq (Llama-3.3-70b) → graphifyy Leiden
         │
         ▼
 [vault_write] ──── Obsidian .md files → vault/
```

### LLM & Embedding Setup

| Component | Purpose | Required |
|-----------|---------|----------|
| **Groq API** | Heavy reasoning: graph building, enrichment, synthesis | ✅ Yes |
| **Local Model** | Batch classification, subtopics | ⭕ Optional |
| **Local Embeddings** | Semantic search (runs on CPU/GPU) | Auto |

**Local model servers supported:** vLLM, llama.cpp, Ollama, LM Studio, or any OpenAI-compatible server. The hybrid client auto-detects whether `/v1/chat/completions/batch` is available and falls back to concurrent individual calls if not.

---

## CLI Commands Reference

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
sg web --no-open                 # Start without auto-opening browser
sg mcp-serve                     # Start Model Context Protocol server (stdio or sse)
```

---

## Configuration

### Web UI (Recommended)

Open `http://localhost:8080/settings` to configure everything from the browser. All settings are encrypted and stored locally in the SQLite database — no `.env` needed.

### `.env` File (Advanced / Fallback)

```ini
# Required — Groq API for taxonomy synthesis & large model tasks
SG_GROQ_API_KEY=gsk_...
SG_GROQ_MODEL=llama-3.3-70b-versatile

# Optional — Local model server (any OpenAI-compatible)
SG_VLLM_BASE_URL=http://localhost:8000   # or ngrok URL
SG_VLLM_MODEL=Qwen/Qwen3.5-9B-FP8

# LinkedIn credentials (only for live scraping / comment fetching)
SG_LINKEDIN_EMAIL=user@example.com
SG_LINKEDIN_PASSWORD=your_password
# OR use session cookie:
SG_LINKEDIN_COOKIE=your_li_at_cookie_value

# Optional overrides (defaults shown)
# SG_DB_PATH=.socialgraph/socialgraph.db
# SG_WORKSPACE_DIR=.socialgraph
# SG_OBSIDIAN_VAULT_PATH=./vault
# SG_BATCH_SIZE=10
# SG_LLM_TIMEOUT=580.0
# SG_MAX_COMMENTS=5
# SG_LOG_LEVEL=INFO
# SG_WEB_PORT=8080
# SG_SCHEDULE_INTERVAL_HOURS=6.0
```

> **Note:** Web UI settings take precedence over `.env` values.

---

## Project Structure

```
socialgraph/            # Main Python source package
  ├── agents/           # Pipeline stage agents (Ingest, Classify, Enrich, etc.)
  ├── cli/              # Modular typer CLI commands
  ├── config/           # Application configuration models
  ├── connectors/       # API and browser scrape integrations
  ├── knowledge/        # Obsidian rendering, search, and graph algorithms
  ├── llm/              # OpenAI/Groq router & hybrid client classes
  ├── storage/          # SQLAlchemy schemas, migrations, repository layer
  └── web/              # FastAPI application, pipeline runner & web assets
tests/                  # Complete test suite (unit, integration, e2e)
vault/                  # Default Obsidian vault output directory (git-ignored)
.socialgraph/           # Default SQLite DB and application cache (git-ignored)
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines. Open-source under the [MIT License](LICENSE).

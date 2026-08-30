# Social Graph (know-ctl)

Transform saved posts from social media platforms into an interactive, interconnected Obsidian knowledge graph.

[![CI](https://github.com/akashrai2003/know-ctl/actions/workflows/ci.yml/badge.svg)](https://github.com/akashrai2003/know-ctl/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/downloads/)

---

## Overview

Social Graph bridges social content consumption and personal knowledge management (PKM). It aggregates high-value saved posts and discussions across your social platforms, crawls and extracts referenced external web articles, scrapes discussion comments, generates local vector embeddings, maps topics using hybrid LLM routing (local models + Groq), clusters communities via the Leiden algorithm, and outputs a linked Obsidian Markdown vault.

While LinkedIn is the initial production connector, Social Graph is engineered as a universal social media knowledge aggregator. Notes are structured in platform-specific subtrees (`linkedin/`, `reddit/`, `x/`, `substack/`) with shared cross-platform topic graphs and semantic similarity links. **Reddit integration is next on the roadmap**, followed by X (Twitter) and Substack.

The project includes a web application with an onboarding wizard, interactive settings dashboard, encrypted credential store, live pipeline runner terminal, and a D3 force-directed knowledge graph. No `.env` file or manual configuration required.

---

## Features

- **Web Dashboard**: Browser interface powered by FastAPI. Configure API keys, upload data files, inspect topics, authors, and graph clusters directly in your browser.
- **Encrypted Local Storage**: Machine-derived Fernet AES encryption stores credentials securely in local SQLite (`.socialgraph/socialgraph.db`).
- **Multi-Platform Architecture**: Platform-partitioned knowledge storage (`linkedin/`, `reddit/`, `x/`) unified by cross-platform topic taxonomies and semantic search.
- **Hybrid LLM Pipeline**:
  - **Local Models** (vLLM, llama.cpp, Ollama, LM Studio): High-throughput classification and batch subtopic detection. Automatically detects `/v1/chat/completions/batch` support and falls back to concurrent async requests when needed.
  - **Groq API**: High-speed reasoning with Qwen and Llama models for community clustering and graph synthesis.
- **Dual Ingestion Modes**: Upload official data archive JSON exports or live-scrape posts and comments using Playwright (credentials or session cookie).
- **Deep URL and Comment Enrichment**: Crawls linked web pages with `trafilatura` and extracts thread discussions to retain full context.
- **Local Vector Embeddings**: Generates embeddings locally using `sentence-transformers` with vectorized matrix similarity calculations.
- **Obsidian Vault Synthesis**: Writes clean Markdown files with YAML frontmatter, bidirectional wikilinks (`[[post_...]]`), topic Maps of Content (MOCs), and author profiles.
- **Model Context Protocol (MCP)**: Query your knowledge graph directly from Claude Desktop or custom AI agent workflows.

---

## Platform Support & Roadmap

| Platform | Ingestion Method | Status | Target Path |
|:---|:---|:---|:---|
| **LinkedIn** | JSON archive export or live Playwright scraping | Supported (v0.1) | `vault/linkedin/` |
| **Reddit** | Saved posts & saved comments (JSON / Reddit API) | Up Next (v0.2) | `vault/reddit/` |
| **X (Twitter)** | Bookmarks export & thread scraping | Planned | `vault/x/` |
| **Substack** | Reading list & saved newsletters | Planned | `vault/substack/` |

---

## Quick Start (Web UI)

No `.env` file required. You can configure and run everything from the browser.

### 1. Clone and Install

```bash
# Clone the repository
git clone https://github.com/akashrai2003/know-ctl.git
cd know-ctl

# Create virtual environment (Python >= 3.10)
python3 -m venv venv
source venv/bin/activate

# Install package
pip install -e .

# Or install with dev/test dependencies
pip install -e ".[dev]"
```

### 2. Initialize and Launch

```bash
# Initialize local database tables and workspace folders
sg init

# Launch the Web Dashboard
sg web
```

Open `http://localhost:8080` in your browser.

### 3. Onboarding Wizard

On first launch, an interactive wizard will guide you through:
1. **Welcome**: Overview of features.
2. **Groq API Key**: Enter your free API key from [console.groq.com](https://console.groq.com) with an instant inline connectivity test.
3. **Local Model Server** (optional): Connect vLLM, llama.cpp, or Ollama (supports auto-batch detection).
4. **LinkedIn Credentials** (optional): Email/password or session cookie (`li_at`) for live scraping.
5. **Ready**: Upload your archive or trigger the pipeline.

### 4. Upload Data Export

In the **Settings** tab, upload your saved posts JSON export:
> LinkedIn -> Settings & Privacy -> Data Privacy -> Get a copy of your data -> select "Saved items".

### 5. Run the Pipeline

Head to the **Pipeline** page and click **Run Pipeline**. Follow real-time execution in the embedded terminal stream.

---

## CLI Setup (.env)

For headless servers or automation scripts, you can supply credentials via environment variables or a `.env` file:

```bash
cp .env.example .env
# Edit .env with your Groq API key and optional endpoints
sg init
sg run
```

Values configured via the Web UI are stored in SQLite and take precedence over `.env` defaults.

---

## Architecture

```text
 Saved Posts (JSON Export or Live Scraper)
                     |
                     v
             +---------------+
             | [1]  Ingest   | ---> SQLite (.socialgraph/socialgraph.db)
             +-------+-------+
                     |
                     v
             +---------------+
             | [2] Comments  | ---> Comment threads & discussions
             +-------+-------+
                     |
                     v
             +---------------+
             | [3]  Enrich   | ---> trafilatura + httpx (external article text)
             +-------+-------+
                     |
                     v
             +---------------+
             | [4] Classify  | ---> Hybrid LLM (vLLM / llama.cpp batch)
             +-------+-------+
                     |
                     v
             +---------------+
             | [5]   Embed   | ---> Local SentenceTransformers (Qwen-0.6B)
             +-------+-------+
                     |
                     v
             +---------------+
             | [6] Graph-Bld | ---> Groq (Llama-3.3-70b / Qwen) -> graphifyy Leiden
             +-------+-------+
                     |
                     v
             +---------------+
             | [7] Vault-Wrt | ---> Markdown files with [[wikilinks]] -> ./vault/{platform}/
             +---------------+
```

### LLM Task Matrix

| Component | Responsibility | Recommended Model | Mode |
|:---|:---|:---|:---|
| **Groq API** | Community detection, graph synthesis, reasoning | `llama-3.3-70b-versatile` / `qwen/qwen3.6-27b` | Cloud API |
| **Local Model** | Fast post topic classification & subtopic mapping | `Qwen/Qwen3.5-9B-FP8` | Batch / Async |
| **Local Embeddings** | Vector similarity & cosine graph edges | `Qwen/Qwen3-Embedding-0.6B` | Local (CUDA/CPU) |

---

## CLI Reference

Social Graph provides the `sg` command-line interface:

```bash
# Core and Status
sg init                          # Initialize database schema and workspace
sg status                        # Display post counts by stage and daemon status

# Pipeline Execution
sg run                           # Run full pipeline end-to-end
sg run --from classify           # Resume starting from a specific stage
sg run --stage enrich            # Execute only one specific stage
sg run --live                    # Use live Playwright scraper instead of JSON

# Individual Stages
sg ingest --json <file>          # Ingest posts from a JSON archive
sg scrape                        # Launch browser to scrape saved posts live
sg comments                      # Fetch post comments and discussion threads
sg enrich                        # Crawl and summarize linked URLs
sg comment-enrich                # Fetch and summarize links inside comments
sg classify                      # Categorize posts according to topic taxonomy
sg embed                         # Compute vector embeddings for all posts
sg subtopic                      # Detect granular subtopics per category
sg semantic-edges                # Build cosine similarity graph edges
sg build-graph                   # Cluster communities using Leiden algorithm
sg vault-write                   # Generate Markdown files in Obsidian vault

# Discovery and Analytics
sg search "vector databases"     # Semantic search over your posts
sg similar "urn:li:activity:..." # Find semantically related posts
sg graph stats                   # Inspect topic and author distributions
sg graph co-occurrence           # Analyze topic co-occurrence patterns
sg graph timeline                # Monthly post activity breakdown

# Background Daemon and Web Server
sg schedule start                # Start background scheduler (syncs every 6h)
sg schedule status               # Check background daemon health
sg schedule stop                 # Stop background scheduler
sg web                           # Launch web dashboard (http://localhost:8080)
sg web --no-open --port 3000     # Run web dashboard on custom port headlessly
sg mcp-serve                     # Start Model Context Protocol server (stdio/http)
```

---

## Configuration Reference

Settings can be managed in **Web UI -> Settings** or set in `.env`:

| Setting | Env Variable | Default | Description |
|:---|:---|:---|:---|
| **Groq API Key** | `SG_GROQ_API_KEY` | `""` | Required for graph reasoning and synthesis |
| **Groq Model** | `SG_GROQ_MODEL` | `llama-3.3-70b-versatile` | Primary reasoning model |
| **Local Model URL** | `SG_VLLM_BASE_URL` | `""` | Local OpenAI-compatible server URL |
| **Local Model ID** | `SG_VLLM_MODEL` | `Qwen/Qwen3.5-9B-FP8` | Model ID for classification |
| **Embedding Model** | `SG_EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-0.6B` | Sentence-transformers model |
| **Embedding Device** | `SG_EMBEDDING_DEVICE` | `cuda` | `cuda`, `cpu`, or `mps` |
| **LinkedIn Email** | `SG_LINKEDIN_EMAIL` | `""` | Account email for live scraping |
| **LinkedIn Password** | `SG_LINKEDIN_PASSWORD` | `""` | Account password for live scraping |
| **LinkedIn Cookie** | `SG_LINKEDIN_COOKIE` | `""` | `li_at` session cookie for MFA bypass |
| **Batch Size** | `SG_BATCH_SIZE` | `10` | Concurrency batch size for LLM calls |
| **Max Comments** | `SG_MAX_COMMENTS` | `5` | Comments per post to scrape |
| **Obsidian Vault** | `SG_OBSIDIAN_VAULT_PATH` | `./vault` | Output directory for Markdown notes |
| **Web Port** | `SG_WEB_PORT` | `8080` | Local dashboard server port |

---

## Repository Structure

```text
know-ctl/
├── socialgraph/
│   ├── agents/          # Pipeline agents (Ingest, Classify, Embed, VaultWrite, etc.)
│   ├── cli/             # Typer CLI subcommands (pipeline, server, schedule, graph)
│   ├── config/          # Pydantic Settings and configuration loader
│   ├── connectors/      # Playwright browser automation and platform connectors
│   ├── knowledge/       # Obsidian formatting, graph layout, semantic search
│   ├── llm/             # Hybrid client, Groq client, prompt templates, factory
│   ├── storage/         # SQLAlchemy models, SQLite migrations, encrypted config store
│   └── web/             # FastAPI app, SSE pipeline runner, static assets (HTML/CSS/JS)
├── tests/               # Pytest suite (unit, API, integration)
├── vault/               # Generated Obsidian knowledge vault (git-ignored)
├── .socialgraph/        # Application database and logs (git-ignored)
├── SETUP.md             # In-depth credential and cookie setup guide
└── pyproject.toml       # Project metadata, dependencies, and tools
```

---

## Contributing

Contributions are welcome. Please check out [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on code formatting (`ruff format`), linting (`ruff check`), and running the test suite (`pytest`).

## License

This project is licensed under the [MIT License](LICENSE).

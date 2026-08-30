<div align="center">

# ⬡ Social Graph (`know-ctl`)

### Transform LinkedIn saved posts into an interactive, interconnected Obsidian knowledge graph.

[![CI](https://github.com/akashrai2003/know-ctl/actions/workflows/ci.yml/badge.svg)](https://github.com/akashrai2003/know-ctl/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Obsidian](https://img.shields.io/badge/Obsidian-Vault%20Ready-7C3AED.svg?logo=obsidian&logoColor=white)](https://obsidian.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

[**Key Features**](#-key-features) • [**Quick Start (Web UI)**](#-quick-start-recommended--web-ui) • [**Architecture**](#-architecture) • [**CLI Reference**](#-cli-reference) • [**Setup Guide**](SETUP.md)

</div>

---

## 📖 Overview

**Social Graph** bridges social content consumption and personal knowledge management (PKM). It ingests your saved LinkedIn posts, crawls and extracts external web links, scrapes high-signal comments, generates local vector embeddings, maps topics using hybrid LLM routing (local models + Groq), detects communities via the Leiden algorithm, and outputs a pristine, linked **Obsidian Markdown Vault**.

It features a **standalone web application** with an onboarding wizard, interactive settings dashboard, encrypted credential store, live pipeline runner terminal, and a D3 force-directed knowledge graph — **no `.env` file or manual configuration required**.

---

## ✨ Key Features

- **🌐 Zero-Config Web Dashboard**: Complete web UI powered by FastAPI with dark-mode glassmorphism. Setup keys, upload files, inspect topics, authors, and graph clusters directly in browser.
- **🔐 Encrypted Local Storage**: Machine-derived Fernet AES encryption stores credentials securely in local SQLite (`.socialgraph/socialgraph.db`).
- **⚡ Hybrid LLM Pipeline**:
  - **Local Models** (vLLM, llama.cpp, Ollama, LM Studio): High-throughput classification and batch subtopic detection. Auto-detects `/v1/chat/completions/batch` and falls back to concurrent async requests seamlessly.
  - **Groq API**: High-speed reasoning with Qwen / Llama models for community clustering and graph synthesis.
- **📥 Dual Ingestion Modes**: Upload LinkedIn's official data archive JSON export, or live-scrape posts and comments using Playwright (email/password or `li_at` session cookie).
- **🔗 Deep URL & Comment Enrichment**: Crawls linked web pages with `trafilatura` and extracts thread discussions to retain complete context.
- **🔢 Local Vector Embeddings & Fast Cosine Search**: Generates embeddings locally using `sentence-transformers` with vectorized matrix similarity calculations.
- **📝 Obsidian Vault Synthesis**: Writes clean Markdown files with YAML frontmatter, bidirectional `[[wikilinks]]`, topic MOCs (Maps of Content), and author profiles.
- **🔌 Model Context Protocol (MCP)**: Query your social knowledge base directly from Claude Desktop or custom AI agents.

---

## ⚡ Quick Start (Recommended — Web UI)

No `.env` file required. You can configure and run everything from the browser.

### 1. Clone & Install

```bash
# Clone the repository
git clone https://github.com/akashrai2003/know-ctl.git
cd know-ctl

# Create virtual environment (Python >= 3.10)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e .

# Or install with development & test tools
pip install -e ".[dev]"
```

### 2. Initialize & Launch

```bash
# Initialize local database tables and workspace folders
sg init

# Launch the Web Dashboard
sg web
```

Open **`http://localhost:8080`** in your browser.

### 3. Onboarding Wizard

On first launch, an interactive 5-step wizard guides you:
1. **Welcome**: Quick tour of features.
2. **Groq API Key**: Enter your free API key from [console.groq.com](https://console.groq.com) with an instant inline connectivity test.
3. **Local Model Server** *(optional)*: Connect vLLM, llama.cpp, or Ollama (supports auto-batch detection).
4. **LinkedIn Credentials** *(optional)*: Email/password or session cookie (`li_at`) for live scraping.
5. **Ready**: Upload your archive or trigger the pipeline.

### 4. Upload LinkedIn Export Data

In the **Settings** tab, drag & drop your `linkedin_saved_posts.json` archive:
> LinkedIn → **Settings & Privacy** → **Data Privacy** → **Get a copy of your data** → select **Saved items**.

### 5. Run the Pipeline

Head to the **⚡ Pipeline** page and click **Run Pipeline**. Follow real-time execution in the embedded terminal stream.

---

## 🖥️ Alternative: CLI Setup (`.env`)

For headless servers or automation scripts, you can supply credentials via environment variables or a `.env` file:

```bash
cp .env.example .env
# Edit .env with your Groq API key and optional endpoints
sg init
sg run
```

> **Note**: Values configured via the Web UI are stored in SQLite and take precedence over `.env` defaults.

---

## 🏗️ Architecture

```text
 linkedin_saved_posts.json (or Playwright Live Scraping)
                     │
                     ▼
             ┌───────────────┐
             │ [1]  Ingest   │ ──► SQLite (.socialgraph/socialgraph.db)
             └───────┬───────┘
                     ▼
             ┌───────────────┐
             │ [2] Comments  │ ──► Voyager API / DOM thread extraction
             └───────┬───────┘
                     ▼
             ┌───────────────┐
             │ [3]  Enrich   │ ──► trafilatura + httpx (external article text)
             └───────┬───────┘
                     ▼
             ┌───────────────┐
             │ [4] Classify  │ ──► Hybrid LLM (vLLM / llama.cpp batch)
             └───────┬───────┘
                     ▼
             ┌───────────────┐
             │ [5]   Embed   │ ──► Local SentenceTransformers (Qwen-0.6B)
             └───────┬───────┘
                     ▼
             ┌───────────────┐
             │ [6] Graph-Bld │ ──► Groq (Llama-3.3-70b / Qwen) → graphifyy Leiden
             └───────┬───────┘
                     ▼
             ┌───────────────┐
             │ [7] Vault-Wrt │ ──► Markdown files with [[wikilinks]] → ./vault
             └───────────────┘
```

### LLM Task Matrix

| Component | Responsibility | Recommended Model | Mode |
|:---|:---|:---|:---:|
| **Groq API** | Community detection, graph synthesis, reasoning | `llama-3.3-70b-versatile` / `qwen/qwen3.6-27b` | Cloud API |
| **Local Model** | Fast post topic classification & subtopic mapping | `Qwen/Qwen3.5-9B-FP8` | Batch / Async |
| **Local Embeddings** | Vector similarity & cosine graph edges | `Qwen/Qwen3-Embedding-0.6B` | Local (CUDA/CPU) |

---

## 💻 CLI Reference

Social Graph provides the `sg` command-line interface for granular control:

```bash
# ── Core & Status ──────────────────────────────────────────────
sg init                          # Initialize database schema and workspace
sg status                        # Display post counts by stage and daemon status

# ── Pipeline Execution ─────────────────────────────────────────
sg run                           # Run full pipeline end-to-end
sg run --from classify           # Resume starting from a specific stage
sg run --stage enrich            # Execute only one specific stage
sg run --live                    # Use live Playwright scraper instead of JSON

# ── Individual Stages ──────────────────────────────────────────
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

# ── Discovery & Analytics ──────────────────────────────────────
sg search "vector databases"     # Semantic search over your posts
sg similar "urn:li:activity:..." # Find semantically related posts
sg graph stats                   # Inspect topic and author distributions
sg graph co-occurrence           # Analyze topic co-occurrence patterns
sg graph timeline                # Monthly post activity breakdown

# ── Background Daemon & Web Server ─────────────────────────────
sg schedule start                # Start background scheduler (syncs every 6h)
sg schedule status               # Check background daemon health
sg schedule stop                 # Stop background scheduler
sg web                           # Launch web dashboard (http://localhost:8080)
sg web --no-open --port 3000     # Run web dashboard on custom port headlessly
sg mcp-serve                     # Start Model Context Protocol server (stdio/http)
```

---

## ⚙️ Configuration Reference

Settings can be managed dynamically in **Web UI → Settings** or set in `.env`:

| Setting | Env Variable | Default | Description |
|:---|:---|:---:|:---|
| **Groq API Key** | `SG_GROQ_API_KEY` | `""` | Required for graph reasoning & synthesis |
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

## 📁 Repository Structure

```text
know-ctl/
├── socialgraph/
│   ├── agents/          # Pipeline agents (Ingest, Classify, Embed, VaultWrite, etc.)
│   ├── cli/             # Typer CLI subcommands (pipeline, server, schedule, graph)
│   ├── config/          # Pydantic Settings and configuration loader
│   ├── connectors/      # Playwright browser automation & LinkedIn scraper
│   ├── knowledge/       # Obsidian formatting, graph layout, semantic search
│   ├── llm/             # Hybrid client, Groq client, prompt templates, factory
│   ├── storage/         # SQLAlchemy models, SQLite migrations, encrypted config store
│   └── web/             # FastAPI app, SSE pipeline runner, static assets (HTML/CSS/JS)
├── tests/               # Pytest suite (unit, API, integration)
├── vault/               # Generated Obsidian knowledge vault (git-ignored)
├── .socialgraph/        # Application database and logs (git-ignored)
├── SETUP.md             # In-depth credential & cookie setup guide
└── pyproject.toml       # Project metadata, dependencies, and tools
```

---

## 🤝 Contributing

Contributions are welcome! Please check out [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on code formatting (`ruff format`), linting (`ruff check`), and running the test suite (`pytest`).

## 📄 License

This project is licensed under the [MIT License](LICENSE).

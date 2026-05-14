# Social Graph

Transform LinkedIn saved posts into a navigable Obsidian knowledge graph.

## What It Does

1. **Ingest** — Import posts from `linkedin_saved_posts.json` (or refresh via browser automation)
2. **Enrich** — Follow external links, extract article text, process comments
3. **Classify** — Assign posts to topics using LLM-powered taxonomy
4. **Build Graph** — Community detection (Leiden algorithm) via graphifyy
5. **Write Vault** — Export to Obsidian: one note per post, topic MOC files, author pages

## Quick Start

```bash
# Prerequisites
python3 -m pip install -e ".[dev]"
python3 -m playwright install chromium --with-deps
cp .env.example .env
# Edit .env with your credentials

# Initialize DB
alembic upgrade head

# Build topic taxonomy (requires Groq API key)
make bootstrap-taxonomy

# Run full pipeline
sg ingest --json linkedin_saved_posts.json
sg run
```

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

### LLM Providers

| Provider | Role | Model |
|----------|------|-------|
| vLLM (self-hosted) | Per-post extraction + classification | `Qwen3.5-9B-FP8` |
| Groq | Taxonomy synthesis + graph structure | `llama-3.3-70b-versatile` |

## CLI Commands

```bash
sg status                        # Show pipeline status
sg ingest --json <file>          # Import posts from JSON
sg enrich                        # Enrich all pending posts
sg classify                      # Classify posts into topics
sg build-graph                   # Build the knowledge graph
sg vault-write                   # Write Obsidian vault
sg run                           # Full pipeline
sg run --from classify           # Resume from a stage
sg run --dry-run                 # Preview without changes
```

## Configuration

Copy `.env.example` to `.env` and fill in:
```
SG_VLLM_BASE_URL=https://your-ngrok-url.ngrok.io
SG_GROQ_API_KEY=your_groq_api_key
SG_LINKEDIN_EMAIL=your@email.com        # only needed for browser refresh
SG_LINKEDIN_PASSWORD=yourpassword       # only needed for browser refresh
```

## Project Structure

```
socialgraph/          Python package
scripts/              One-time scripts (bootstrap_taxonomy.py)
tests/                unit/, integration/, e2e/
vault/                Obsidian vault (git-ignored)
.socialgraph/         DB + browser state (git-ignored)
.claude/skills/       Implementation knowledge files
```

## Extending to Other Platforms

See `.claude/skills/social-media-extraction/SKILL.md` — "Adding a New Platform".

Planned: Twitter/X bookmarks, Reddit saved posts, Substack subscriptions.

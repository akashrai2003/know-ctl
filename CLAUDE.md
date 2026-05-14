# Social Graph — AI Agent Guide

## Project Purpose

Transform LinkedIn saved posts into an Obsidian knowledge graph. Posts are classified into topics, enriched with external link content, and written to a navigable vault.

## Tech Stack

- **Python 3.12+**, SQLAlchemy 2 async, Alembic, aiosqlite
- **LLM**: Qwen3.5-9B-FP8 via vLLM (batch, small tasks) + Groq (large tasks)
- **Browser**: Playwright async API for LinkedIn refresh
- **Graph**: graphifyy[leiden] for community detection + Obsidian export
- **CLI**: `sg` (typer), `make` shortcuts

## Key Commands

```bash
make install-dev    # Install everything
make migrate        # Create/update DB
make bootstrap-taxonomy  # Build topic taxonomy from posts
sg ingest --json linkedin_saved_posts.json
sg run              # Full pipeline
sg status           # Show run stats
make test           # Run all tests
```

## Repository Layout

```
socialgraph/       Main Python package
  agents/          Stage agents (ingest, enrich, classify, graph_build, vault_write)
  browser/         Playwright client + JS scripts
  cli/             Typer CLI commands
  config/          Settings (pydantic-settings, SG_ prefix)
  connectors/      Platform connectors (linkedin, base)
  knowledge/       taxonomy.py, obsidian.py, graph.py
  llm/             router.py, small_client.py (vLLM), large_client.py (Groq)
  pipeline/        orchestrator.py, hashing.py, stages.py
  storage/         models.py (ORM), db.py, repo.py
alembic/           DB migrations
scripts/           bootstrap_taxonomy.py + evals
tests/             unit/, integration/, e2e/
vault/             Obsidian vault output (git-ignored)
.socialgraph/      Runtime DB + browser state (git-ignored)
```

## Environment Variables (SG_ prefix)

See `.env.example` for all variables. Required ones:
- `SG_VLLM_BASE_URL` — ngrok URL of vLLM server
- `SG_GROQ_API_KEY` — Groq API key
- `SG_LINKEDIN_EMAIL` / `SG_LINKEDIN_PASSWORD` — for browser refresh only

## Skills

- `.claude/skills/social-media-extraction/SKILL.md` — LinkedIn Voyager API, pagination
- `.claude/skills/llm-routing/SKILL.md` — dual-model routing, batch client
- `.claude/skills/obsidian-knowledge-graph/SKILL.md` — graphifyy, YAML safety, vault structure
- `.claude/skills/browser-automation/SKILL.md` — Playwright, session persistence
- `.claude/skills/content-enrichment/SKILL.md` — URL enrichment, trafilatura, comment processing
- `.claude/skills/knowledge-pipeline/SKILL.md` — stage contracts, checkpoints, parallelism

## Pipeline Stages

```
ingest → enrich → classify → graph_build → vault_write
```

Each stage writes a `StageCheckpoint` — re-runs skip already-processed items.

## LLM Routing Rules

- **Small tasks** (per-post, high volume): vLLM batch endpoint
- **Large tasks** (taxonomy, graph structure): Groq
- Always include `chat_template_kwargs: {"enable_thinking": false}` for vLLM

## YAML Safety

All user content in Obsidian frontmatter MUST go through `_yaml_str()` from `socialgraph/knowledge/obsidian.py`. Never write raw strings from post content into YAML.

## Database

SQLite at `.socialgraph/socialgraph.db`. Key tables:
- `posts` — one row per LinkedIn post
- `topics` — taxonomy topics
- `post_topics` — M2M with confidence score
- `external_links` — discovered URLs (deduped)
- `pipeline_runs` + `stage_checkpoints` — idempotency

## Testing

```bash
pytest tests/unit/        # pure unit tests, no I/O
pytest tests/integration/ # requires .env with valid API keys
pytest tests/e2e/         # runs full pipeline against sample fixtures
```

## Extending to New Platforms

See `.claude/skills/social-media-extraction/SKILL.md` — "Adding a New Platform" section.

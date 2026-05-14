# Social Graph — Autonomous Agent Guide

## Project Purpose

Build and maintain a knowledge graph from social media saved posts. The primary data source is LinkedIn (1508 posts exported via browser). The graph is exported as an Obsidian vault.

## Allowed Autonomous Actions

- Read any file in the repository
- Run `make test` and `make lint`
- Run `sg status` and `sg run --dry-run`
- Run database migrations: `alembic upgrade head`
- Create/edit files in `socialgraph/`, `tests/`, `scripts/`, `docs/`
- Write to `vault/` (Obsidian output)

## Requires User Confirmation Before Doing

- `sg ingest --json ...` (writes to DB)
- `sg run` (full pipeline — triggers LLM API calls)
- `make bootstrap-taxonomy` (Groq API calls)
- Any operation touching `.socialgraph/` directly
- Dropping DB tables
- `git push`

## Architecture Notes

### Pipeline
```
ingest → enrich → classify → graph_build → vault_write
```
All stages are idempotent — re-running skips already-processed items.

### LLM Routing
- Small/batch tasks → vLLM (Qwen3.5-9B-FP8) at `SG_VLLM_BASE_URL`
- Critical/architectural tasks → Groq at `https://api.groq.com/openai/v1`
- Always set `chat_template_kwargs: {"enable_thinking": false}` on vLLM calls

### Skills Reference
All detailed implementation knowledge is in `.claude/skills/`:
- `social-media-extraction/SKILL.md` — LinkedIn pagination, post detection
- `llm-routing/SKILL.md` — routing table, BatchLLMClient, GroqClient
- `obsidian-knowledge-graph/SKILL.md` — graphifyy, vault structure, YAML safety
- `browser-automation/SKILL.md` — Playwright login, script injection, selectors
- `content-enrichment/SKILL.md` — URL filtering, trafilatura, dedup
- `knowledge-pipeline/SKILL.md` — stage contracts, checkpoints, error recovery

### Security Rules
1. Never log `SG_LINKEDIN_EMAIL`, `SG_LINKEDIN_PASSWORD`, `SG_GROQ_API_KEY`
2. All YAML frontmatter values must go through `_yaml_str()` from `socialgraph/knowledge/obsidian.py`
3. URL fetching must enforce `MAX_RESPONSE_BYTES = 2_000_000` and `FETCH_TIMEOUT = 10.0`
4. Never write credentials to any file in the vault

### Testing Strategy
- Unit tests: no I/O, mock LLM clients
- Integration tests: require `.env` with real credentials
- E2E tests: run full pipeline against `tests/fixtures/sample_posts.json`

## Key Files

| File | Purpose |
|------|---------|
| `socialgraph/config/settings.py` | All env vars, SG_ prefix |
| `socialgraph/storage/models.py` | SQLAlchemy ORM models |
| `socialgraph/llm/router.py` | LLM routing logic |
| `socialgraph/pipeline/orchestrator.py` | Stage orchestration + checkpoints |
| `socialgraph/knowledge/obsidian.py` | YAML safety + vault writer |
| `scripts/bootstrap_taxonomy.py` | One-time taxonomy builder |
| `alembic/versions/0001_initial.py` | DB schema migration |

## Common Patterns

When adding a new pipeline stage:
1. Create agent in `socialgraph/agents/{stage}_agent.py` implementing `Agent` protocol
2. Register in `socialgraph/pipeline/orchestrator.py`
3. Add CLI command in `socialgraph/cli/main.py`
4. Write unit test in `tests/unit/test_{stage}_agent.py`
5. Add `StageCheckpoint.stage` value to checkpoint table

When adding a new LLM task:
1. Add task name to `ROUTING_TABLE` in `socialgraph/llm/router.py`
2. Add prompt template to `socialgraph/llm/prompts.py`
3. If task uses structured output, define Pydantic model in the same module

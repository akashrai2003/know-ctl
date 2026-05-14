# Milestone 10 — Production Grade

> Parent plan: [`../vision.md`](../vision.md)
> Predecessor: [`milestone9.md`](./milestone9.md)
> Owner: 1 engineer · Timebox: ~5 days · Status: 🔲 Not started

---

## 1. Goal

Make the system deployable, observable, and resilient. Docker + compose for one-command startup, LLM response caching so re-runs never re-spend tokens, Prometheus metrics for pipeline health, and backup/restore for the full knowledge base. The system should run unattended for weeks without manual intervention.

---

## 2. Exit Criteria

- [ ] `docker compose up` starts: sqlite-backed app container, vLLM endpoint (config-only, external GPU required), and optional Grafana+Prometheus stack.
- [ ] `Dockerfile`: non-root user, multi-stage build, minimal image (<500MB without vLLM).
- [ ] **LLM response cache**: SHA-256 keyed JSON cache at `.socialgraph/llm_cache/`. All LLM calls (vLLM + Groq) check cache before making HTTP requests. Cache hit logged as `llm.cache_hit`. `sg cache stats` shows hit rate + estimated token savings.
- [ ] `sg cache clear [--older-than N-days]` pruning command.
- [ ] **Prometheus metrics** exported at `GET /metrics` on web server:
  - `sg_llm_call_duration_seconds` histogram (provider, model, task labels)
  - `sg_llm_tokens_total` counter (provider, model, direction=prompt|completion)
  - `sg_pipeline_stage_duration_seconds` histogram (stage label)
  - `sg_posts_total` gauge (status label)
  - `sg_llm_cache_hits_total` / `sg_llm_cache_misses_total` counters
- [ ] Grafana dashboard JSON (`docs/grafana-dashboard.json`) with panels for LLM latency, token cost, pipeline throughput, and cache hit rate.
- [ ] `sg backup [--output PATH]` → tar.gz of `{db, llm_cache, vault, taxonomy, logs}`.
- [ ] `sg restore --from PATH` → unpacks backup, verifies integrity (SHA-256 manifest).
- [ ] Config validation on `sg init` and every pipeline start: check DB readable, vLLM reachable, Groq key valid, vault path writable. Fail fast with clear error messages.
- [ ] `ruff check` + `mypy --strict` (on new M10 code) passes.

---

## 3. Action Points

### Day 1 — LLM Response Cache

- **AP-10.1** `socialgraph/llm/cache.py`: `LLMCache`.
  - `key(model, messages, response_format, temperature) -> str`: SHA-256 of JSON-serialized args.
  - `get(key) -> dict | None`: read from `.socialgraph/llm_cache/{key[:2]}/{key}.json`.
  - `set(key, request, response, metadata)`: write JSON with `{key, model, created_at, prompt_tokens, completion_tokens, response}`.
  - Two-level directory to avoid inode limits: `{key[:2]}/{key}.json`.
- **AP-10.2** `GroqClient.complete()`: check `LLMCache.get()` before API call. On miss, call API, then `LLMCache.set()`. Log `llm.cache_hit` at DEBUG.
- **AP-10.3** `BatchLLMClient.batch_chat()`: cache is per-message-list (not per-batch — individual messages are hashed). Check cache for each message, only call vLLM for misses, reassemble results.
- **AP-10.4** `sg cache stats` CLI: total entries, total size, hit count (from log parsing or counter file), estimated tokens saved.
- **AP-10.5** `sg cache clear [--older-than N]` CLI: removes cache files older than N days.

### Day 2 — Prometheus Metrics

- **AP-10.6** Add `prometheus-client` to `pyproject.toml`.
- **AP-10.7** `socialgraph/metrics.py`: define all metrics objects (histograms, counters, gauges) as module-level singletons.
- **AP-10.8** Instrument `GroqClient.complete()` and `BatchLLMClient.batch_chat()`: observe `sg_llm_call_duration_seconds`, increment `sg_llm_tokens_total`, increment cache hit/miss counters.
- **AP-10.9** Instrument pipeline stage agents: each agent's `run()` wraps with `sg_pipeline_stage_duration_seconds.labels(stage=self.name).time()`.
- **AP-10.10** `GET /metrics` endpoint on web server (FastAPI): returns Prometheus text exposition format via `generate_latest()`.
- **AP-10.11** `sg_posts_total` gauge: updated at end of each pipeline run.

### Day 3 — Config Validation + Docker

- **AP-10.12** `socialgraph/config/validator.py`: `ConfigValidator.validate(settings)` — async checks: DB file readable, vLLM `/v1/models` reachable (3s timeout), Groq API key valid (1-token test call), vault path writable. Returns list of `ValidationError`.
- **AP-10.13** Wire `ConfigValidator` into `sg init` and at start of each CLI pipeline command. Print clear error table on failure; exit code 1.
- **AP-10.14** `Dockerfile`: multi-stage (builder → runtime). Non-root user `sguser`. Install only runtime deps. WORKDIR `/app`. Entrypoint `sg`.
- **AP-10.15** `docker-compose.yml`: `socialgraph` service (app), `prometheus` service, `grafana` service. Volumes for `.socialgraph/` (DB + cache + logs) and vault path.
- **AP-10.16** `docs/grafana-dashboard.json`: pre-built dashboard with 6 panels: LLM latency P50/P95, token cost over time, pipeline stage durations, post status funnel, cache hit rate.

### Day 4 — Backup / Restore

- **AP-10.17** `sg backup [--output PATH]`: creates tar.gz containing: `{.socialgraph/socialgraph.db, .socialgraph/llm_cache/, .socialgraph/logs/, topic_taxonomy.json}` + SHA-256 manifest JSON.
- **AP-10.18** `sg restore --from PATH`: extract, verify manifest hashes, restore files to workspace. Prompt for confirmation if existing DB found.
- **AP-10.19** Backup excludes vault (Obsidian handles its own sync); documents this clearly in help text.

### Day 5 — Hardening + Final E2E

- **AP-10.20** Add retry logic to `BatchLLMClient.batch_chat()`: on `httpx.TimeoutException` or 5xx, retry up to 3 times with exponential backoff (1s, 2s, 4s). Log `vllm.retry` at WARNING.
- **AP-10.21** Add `--dry-run` flag to `sg run` / `sg classify` / `sg build-graph`: print what would be processed, make no DB writes.
- **AP-10.22** `mypy --strict` on `socialgraph/llm/`, `socialgraph/metrics.py`, `socialgraph/config/validator.py`. Fix all type errors.
- **AP-10.23** E2E: `docker compose up -d`, run `sg status`, `sg search "transformers"`, `curl /metrics` → assert Prometheus text with `sg_posts_total`.
- **AP-10.24** Update `README.md` with: Docker quickstart, Claude Desktop MCP config, env var reference table, backup/restore instructions.

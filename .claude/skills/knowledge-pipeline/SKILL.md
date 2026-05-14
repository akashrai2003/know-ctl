---
name: knowledge-pipeline
description: Multi-stage pipeline orchestration for social-graph. Covers stage contracts, StageCheckpoint idempotency, SHA-256 input hashing, asyncio.gather parallelism, error recovery policy (failed posts don't halt pipeline), batch sizing, and re-run semantics.
origin: social-graph
---

# Knowledge Pipeline

Use this skill when adding new pipeline stages, modifying orchestration, or implementing re-run/checkpoint behavior.

## Pipeline Stages

```
ingest → enrich → classify → graph_build → vault_write
```

| Stage | Input | Output | LLM | Notes |
|-------|-------|--------|-----|-------|
| `ingest` | Raw JSON / Playwright scrape | `Post` rows in DB | None | Dedup by URN |
| `enrich` | `Post` with raw content | `ExternalLink`, `Comment` rows | Small (batch) | URL fetch + comment extract |
| `classify` | `Post` + enrichment data | `PostTopic` rows | Small (batch) | Topic assignment |
| `graph_build` | All `PostTopic` / `Post` rows | Graph nodes + edges | Large (once) | Leiden community detect |
| `vault_write` | Graph + Post data | `.md` files in vault | None | Obsidian note writing |

---

## Stage Contracts

Each agent implements the `Agent` protocol:

```python
# socialgraph/agents/base.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class Agent(Protocol):
    name: str

    async def run(self, ctx: StageContext) -> StageOutput: ...

@dataclass
class StageContext:
    run_id: str
    settings: Settings
    db: AsyncSession
    stage: str
    batch_ids: list[int] | None = None     # None → process all pending

@dataclass
class StageOutput:
    processed: int
    skipped: int
    failed: int
    stage: str
    meta: dict = field(default_factory=dict)
```

---

## StageCheckpoint — Idempotency

Every stage writes a checkpoint before and after. Re-running the same stage with the same inputs is a no-op.

```python
# alembic/versions/0001_initial.py — StageCheckpoint table
# Unique constraint: (run_id, stage, input_hash)

@dataclass
class CheckpointKey:
    run_id: str
    stage: str
    input_hash: str    # SHA-256 (see below)
```

### Computing `input_hash`

```python
import hashlib

def compute_input_hash(
    stage_name: str,
    input_ids: list[int],
    model_id: str,
    version: int,
) -> str:
    """Deterministic SHA-256 hash for stage input fingerprint."""
    parts = [
        stage_name,
        ",".join(str(i) for i in sorted(input_ids)),
        model_id,
        str(version),
    ]
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
```

`version` is a hand-bumped integer in the agent class (`CHECKPOINT_VERSION = 1`). Bump it when the agent prompt or schema changes to force re-processing.

### Checkpoint Lookup (at stage start)

```python
async def check_stage_checkpoint(
    session: AsyncSession,
    key: CheckpointKey,
) -> bool:
    """Return True if this exact input was already processed successfully."""
    row = await session.scalar(
        select(StageCheckpoint)
        .where(
            StageCheckpoint.run_id == key.run_id,
            StageCheckpoint.stage == key.stage,
            StageCheckpoint.input_hash == key.input_hash,
            StageCheckpoint.status == "ok",
        )
    )
    return row is not None

async def write_checkpoint(
    session: AsyncSession,
    key: CheckpointKey,
    status: str,
    meta: dict,
) -> None:
    ckpt = StageCheckpoint(
        run_id=key.run_id,
        stage=key.stage,
        input_hash=key.input_hash,
        status=status,
        meta_json=json.dumps(meta),
        completed_at=datetime.utcnow(),
    )
    session.add(ckpt)
    await session.commit()
```

---

## Error Recovery Policy

```
Per-post failures → Post.status = "failed" → pipeline continues
Stage-level failures → abort run, write checkpoint status="error"
```

```python
async def run_with_recovery(agent: Agent, ctx: StageContext) -> StageOutput:
    processed = skipped = failed = 0
    async for batch in iter_batches(ctx.batch_ids, ctx.settings.batch_size):
        for item_id in batch:
            try:
                await agent.process_one(item_id, ctx)
                processed += 1
            except Exception as exc:
                logger.error(
                    "stage.item_failed",
                    stage=ctx.stage,
                    item_id=item_id,
                    error=str(exc),
                )
                await mark_failed(ctx.db, item_id, ctx.stage, exc)
                failed += 1
    return StageOutput(processed=processed, skipped=skipped, failed=failed, stage=ctx.stage)
```

**Re-run behavior:** failed posts are included in the next run's input. Check `Post.status != "ok"` to select unprocessed posts.

---

## Parallelism Pattern

For per-post operations within a stage, use `asyncio.gather()`:

```python
CONCURRENCY = 20   # concurrent tasks within a stage (tunable)

async def process_batch_parallel(
    items: list[int],
    process_fn: Callable[[int], Coroutine],
) -> list[StageOutput]:
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def bounded(item_id: int) -> StageOutput:
        async with semaphore:
            return await process_fn(item_id)

    return await asyncio.gather(*[bounded(i) for i in items])
```

Do not use `asyncio.gather()` across stage boundaries — stages must execute sequentially.

---

## Batch Size

```python
# settings.py
batch_size: int = 10   # SG_BATCH_SIZE env var

# Usage in classify_agent.py:
for i in range(0, len(posts), settings.batch_size):
    batch = posts[i : i + settings.batch_size]
    results = await llm_client.batch_chat([make_prompt(p) for p in batch])
```

vLLM batch endpoint processes all items in a single HTTP request. Do not batch more than 20 posts without measuring memory on the vLLM server.

---

## Full Pipeline Orchestrator

```python
# socialgraph/pipeline/orchestrator.py

STAGE_ORDER = ["ingest", "enrich", "classify", "graph_build", "vault_write"]

class PipelineOrchestrator:
    def __init__(self, agents: dict[str, Agent], settings: Settings, db: AsyncSession):
        self._agents = agents
        self._settings = settings
        self._db = db

    async def run(self, run_id: str, start_from: str | None = None) -> PipelineResult:
        stages = STAGE_ORDER
        if start_from:
            stages = stages[stages.index(start_from):]

        results: list[StageOutput] = []
        for stage in stages:
            agent = self._agents[stage]
            ctx = StageContext(run_id=run_id, settings=self._settings, db=self._db, stage=stage)
            output = await run_with_recovery(agent, ctx)
            results.append(output)
            logger.info("stage.complete", **asdict(output))

            if output.failed > 0 and output.processed == 0:
                logger.error("stage.all_failed_abort", stage=stage)
                break

        return PipelineResult(run_id=run_id, stages=results)
```

---

## PipelineRun DB Record

```python
# Updated at stage completion:
run.stage_counts_json = json.dumps({
    stage: {"processed": o.processed, "skipped": o.skipped, "failed": o.failed}
    for stage, o in zip(stages, results)
})
run.status = "ok" if all(o.failed < o.processed for o in results) else "partial"
run.completed_at = datetime.utcnow()
```

---

## CLI: Run Specific Stages

```bash
sg run                          # full pipeline
sg run --from classify          # resume from classify
sg run --stage ingest           # one stage only
sg run --dry-run                # show what would be processed, no changes
```

`--dry-run` prints a summary (post count, pending URLs, etc.) without writing to DB or vault.

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from socialgraph.agents.base import Agent, StageContext, StageOutput
from socialgraph.config.settings import Settings
from socialgraph.storage.db import get_session
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)

STAGE_ORDER = [
    "ingest",
    "comments",
    "comment_enrich",
    "enrich",
    "classify",
    "embed",
    "subtopic",
    "semantic_edges",
    "graph_build",
    "vault_write",
]


@dataclass
class PipelineResult:
    run_id: str
    stages: list[StageOutput] = field(default_factory=list)
    status: str = "ok"


class PipelineOrchestrator:
    def __init__(
        self,
        agents: dict[str, Agent],
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._agents = agents
        self._settings = settings
        self._factory = session_factory

    async def run(
        self,
        start_from: str | None = None,
        only_stage: str | None = None,
        dry_run: bool = False,
    ) -> PipelineResult:
        run_id = str(uuid.uuid4())[:8]
        stages = STAGE_ORDER

        if only_stage:
            if only_stage not in stages:
                raise ValueError(f"Unknown stage: {only_stage!r}")
            stages = [only_stage]
        elif start_from:
            if start_from not in stages:
                raise ValueError(f"Unknown stage: {start_from!r}")
            stages = stages[stages.index(start_from) :]

        if dry_run:
            logger.info("pipeline.dry_run", stages=stages)
            return PipelineResult(run_id=run_id, status="dry_run")

        results: list[StageOutput] = []
        async with get_session(self._factory) as session:
            repo = Repo(session)
            await repo.create_pipeline_run(run_id)
            await session.commit()

        for stage_name in stages:
            agent = self._agents.get(stage_name)
            if agent is None:
                logger.warning("pipeline.missing_agent", stage=stage_name)
                continue

            logger.info("pipeline.stage_start", stage=stage_name, run_id=run_id)
            async with get_session(self._factory) as session:
                ctx = StageContext(
                    run_id=run_id,
                    settings=self._settings,
                    db=session,
                    stage=stage_name,
                )
                output = await agent.run(ctx)

            results.append(output)
            logger.info("pipeline.stage_done", **asdict(output))

            if output.failed > 0 and output.processed == 0 and output.skipped == 0:
                logger.error("pipeline.stage_all_failed", stage=stage_name)
                break

        status = "ok" if all(o.failed == 0 for o in results) else "partial"
        async with get_session(self._factory) as session:
            run_record = await Repo(session).get_pipeline_run(run_id)
            if run_record:
                import json
                run_record.stage_counts_json = json.dumps(
                    {o.stage: asdict(o) for o in results}
                )
                run_record.status = status
                run_record.completed_at = datetime.utcnow()

        return PipelineResult(run_id=run_id, stages=results, status=status)

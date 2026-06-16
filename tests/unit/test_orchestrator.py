"""Unit tests for PipelineOrchestrator."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.agents.base import Agent, StageContext, StageOutput
from socialgraph.pipeline.orchestrator import PipelineOrchestrator, PipelineResult
from socialgraph.storage.db import build_session_factory
from socialgraph.storage.models import PipelineRun


class DummyAgent(Agent):
    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, _ctx: StageContext) -> StageOutput:
        return StageOutput(stage=self.name, processed=1, skipped=2, failed=0)


@pytest.mark.asyncio
async def test_orchestrator_dry_run(test_settings) -> None:
    factory = build_session_factory(test_settings.db_path)
    agents = {"ingest": DummyAgent("ingest"), "enrich": DummyAgent("enrich")}

    orchestrator = PipelineOrchestrator(agents, test_settings, factory)
    res = await orchestrator.run(dry_run=True)

    assert isinstance(res, PipelineResult)
    assert res.status == "dry_run"
    assert len(res.stages) == 0


@pytest.mark.asyncio
async def test_orchestrator_full_run(db_session: AsyncSession, test_settings) -> None:
    # We pass the db_session to ensure DB is initialized, but orchestrator uses factory
    factory = build_session_factory(test_settings.db_path)

    agents = {
        "ingest": DummyAgent("ingest"),
        "enrich": DummyAgent("enrich"),
    }

    orchestrator = PipelineOrchestrator(agents, test_settings, factory)
    res = await orchestrator.run(only_stage="ingest")

    assert res.status == "ok"
    assert len(res.stages) == 1
    assert res.stages[0].stage == "ingest"
    assert res.stages[0].processed == 1

    # Verify pipeline run record created in DB
    runs = (await db_session.scalars(select(PipelineRun))).all()
    assert len(runs) == 1
    assert runs[0].run_id == res.run_id
    assert runs[0].status == "ok"


@pytest.mark.asyncio
async def test_orchestrator_invalid_stage(test_settings) -> None:
    factory = build_session_factory(test_settings.db_path)
    orchestrator = PipelineOrchestrator({}, test_settings, factory)

    with pytest.raises(ValueError, match="Unknown stage"):
        await orchestrator.run(only_stage="invalid-stage")

    with pytest.raises(ValueError, match="Unknown stage"):
        await orchestrator.run(start_from="invalid-stage")

"""E2E test: run full pipeline against sample fixture posts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from socialgraph.agents.base import StageContext
from socialgraph.agents.ingest_agent import IngestAgent
from socialgraph.config.settings import Settings
from socialgraph.storage.db import build_session_factory, create_all_tables


@pytest.fixture
def sample_posts_json(tmp_path: Path) -> Path:
    posts = [
        {
            "urn": f"urn:li:activity:{1000 + i}",
            "author": f"Author {i}",
            "content": f"Post {i} about AI and machine learning tools.",
        }
        for i in range(5)
    ]
    p = tmp_path / "posts.json"
    p.write_text(json.dumps(posts))
    return p


@pytest.fixture
async def test_settings(tmp_path: Path) -> Settings:
    settings = Settings(
        db_path=tmp_path / ".socialgraph" / "test.db",
        workspace_dir=tmp_path / ".socialgraph",
        obsidian_vault_path=tmp_path / "vault",
        vllm_base_url="http://localhost:9999",  # not used in ingest
        groq_api_key="test-key",
    )
    settings.ensure_workspace()
    await create_all_tables(settings.db_path)
    return settings


@pytest.mark.asyncio
async def test_ingest_stage(sample_posts_json: Path, test_settings: Settings):
    factory = build_session_factory(test_settings.db_path)
    from socialgraph.storage.db import get_session

    async with get_session(factory) as session:
        agent = IngestAgent(sample_posts_json)
        ctx = StageContext(
            run_id="e2e-test",
            settings=test_settings,
            db=session,
            stage="ingest",
        )
        output = await agent.run(ctx)

    assert output.processed == 5
    assert output.skipped == 0
    assert output.failed == 0


@pytest.mark.asyncio
async def test_ingest_idempotent(sample_posts_json: Path, test_settings: Settings):
    """Running ingest twice skips already-ingested posts."""
    factory = build_session_factory(test_settings.db_path)
    from socialgraph.storage.db import get_session

    async with get_session(factory) as session:
        agent = IngestAgent(sample_posts_json)
        ctx = StageContext(run_id="e2e-1", settings=test_settings, db=session, stage="ingest")
        await agent.run(ctx)

    async with get_session(factory) as session:
        agent = IngestAgent(sample_posts_json)
        ctx = StageContext(run_id="e2e-2", settings=test_settings, db=session, stage="ingest")
        output = await agent.run(ctx)

    assert output.processed == 0
    assert output.skipped == 5

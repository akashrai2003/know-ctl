"""Regression tests for article-summary backfills on completed posts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.agents.base import StageContext
from socialgraph.agents.enrich_agent import EnrichAgent
from socialgraph.storage.models import ExternalLink, Post, PostExternalLink


@pytest.mark.asyncio
async def test_enrich_summarizes_existing_link_when_no_posts_need_fetching(
    db_session: AsyncSession, test_settings
):
    post = Post(
        urn="urn:li:activity:existing-link",
        platform="linkedin",
        content="Completed post",
        status="ok",
    )
    link = ExternalLink(
        url="https://example.com/article",
        title="Article",
        body_excerpt="A substantial article body. " * 20,
        fetch_status="ok",
    )
    db_session.add_all([post, link])
    await db_session.flush()
    db_session.add(PostExternalLink(post_id=post.id, external_link_id=link.id, context="body"))
    await db_session.commit()

    batch_client = SimpleNamespace(
        batch_chat=AsyncMock(return_value=["A grounded article summary."])
    )
    router = SimpleNamespace(batch_client=batch_client)
    output = await EnrichAgent(router=router).run(
        StageContext("test", test_settings, db_session, "enrich")
    )

    assert output.processed == 0
    assert output.meta["summarized"] == 1
    assert link.ai_summary == "A grounded article summary."
    assert Path(test_settings.workspace_dir, "logs", "summarization.jsonl").exists()

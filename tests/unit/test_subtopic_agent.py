"""Tests for primary-topic-only subtopic generation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.agents.base import StageContext
from socialgraph.agents.subtopic_agent import SubtopicAgent, _safe_subtopic_merge
from socialgraph.llm.router import LLMRouter
from socialgraph.llm.small_client import BatchLLMClient
from socialgraph.storage.models import Post, PostSubtopic, PostTopic, Topic


@pytest.mark.asyncio
async def test_force_subtopic_keeps_only_primary_hierarchy(
    db_session: AsyncSession, test_settings
) -> None:
    post = Post(
        urn="urn:li:activity:subtopic-primary",
        platform="linkedin",
        content="CUDA kernels improve inference throughput.",
        status="classified",
    )
    primary = Topic(name="AI Infrastructure")
    secondary = Topic(name="AI Agents & Automation")
    db_session.add_all([post, primary, secondary])
    await db_session.flush()
    db_session.add_all(
        [
            PostTopic(post_id=post.id, topic_id=primary.id, confidence_score=0.95),
            PostTopic(post_id=post.id, topic_id=secondary.id, confidence_score=0.80),
            PostSubtopic(post_id=post.id, topic_id=secondary.id, subtopic_name="Agent Development"),
        ]
    )
    await db_session.commit()

    batch = MagicMock(spec=BatchLLMClient)
    batch.batch_chat = AsyncMock(
        return_value=[
            {
                "title": "CUDA Kernels for Inference\nMemory Access Drives Throughput",
                "subtopic": "GPU Optimization",
                "summary": "The post explains why memory access dominates kernel performance.",
            }
        ]
    )
    output = await SubtopicAgent(LLMRouter(batch, None), force=True).run(
        StageContext("test", test_settings, db_session, "subtopic")
    )

    rows = list(
        (
            await db_session.execute(
                select(PostSubtopic, Topic.name)
                .join(Topic, Topic.id == PostSubtopic.topic_id)
                .where(PostSubtopic.post_id == post.id)
            )
        ).all()
    )
    assert output.processed == 1
    assert output.failed == 0
    assert [(row.PostSubtopic.subtopic_name, row.name) for row in rows] == [
        ("GPU Optimization", "AI Infrastructure")
    ]
    assert post.title.startswith("CUDA Kernels")


def test_subtopic_merge_guard_accepts_only_near_duplicate_names() -> None:
    known = {
        ("reinforcement", "learning"),
        ("deep", "learning", "application"),
        ("interview", "preparation"),
        ("job", "opportunity"),
    }
    assert _safe_subtopic_merge(
        "Reinforcement Learning", "Reinforcement Learning Algorithms", known
    )
    assert _safe_subtopic_merge("Interview Preparation", "Interview Preparation Strategies", known)
    assert not _safe_subtopic_merge("Deep Learning Applications", "Time Series Forecasting", known)
    assert not _safe_subtopic_merge("Job Opportunities", "Remote Work Opportunities", known)

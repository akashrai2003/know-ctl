"""Tests for replacement-safe, primary-first topic classification."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.agents.base import StageContext
from socialgraph.agents.classify_agent import ClassifyAgent
from socialgraph.knowledge.taxonomy import Taxonomy, TopicDefinition
from socialgraph.llm.router import LLMRouter
from socialgraph.llm.small_client import BatchLLMClient
from socialgraph.storage.models import Post, PostSubtopic, PostTopic, Topic


def _taxonomy() -> Taxonomy:
    return Taxonomy(
        [
            TopicDefinition("AI Agents & Automation", "Autonomous planning and tool use"),
            TopicDefinition("AI Infrastructure", "GPU inference, KV caches, CUDA, and serving"),
            TopicDefinition("Large Language Models", "Language-model architectures"),
        ]
    )


@pytest.mark.asyncio
async def test_force_classification_replaces_old_taxonomy_and_preserves_primary_order(
    db_session: AsyncSession, test_settings
) -> None:
    post = Post(
        urn="urn:li:activity:classification-replace",
        platform="linkedin",
        content="An agent uses a CUDA kernel to reduce KV-cache inference latency.",
        status="ok",
    )
    old_topic = Topic(name="AI Agents & Automation")
    db_session.add_all([post, old_topic])
    await db_session.flush()
    db_session.add_all(
        [
            PostTopic(post_id=post.id, topic_id=old_topic.id, confidence_score=0.95),
            PostSubtopic(post_id=post.id, topic_id=old_topic.id, subtopic_name="Agent Development"),
        ]
    )
    await db_session.commit()

    batch = MagicMock(spec=BatchLLMClient)
    batch.batch_chat = AsyncMock(
        return_value=[
            {
                "primary_topic": "AI Infrastructure",
                "secondary_topics": ["Large Language Models", "AI Agents & Automation"],
                "confidence": 0.96,
            }
        ]
    )
    output = await ClassifyAgent(
        LLMRouter(batch, None),
        _taxonomy(),
        force=True,
        fallback_to_groq=False,
    ).run(StageContext("test", test_settings, db_session, "classify"))

    await db_session.refresh(post, ["post_topics", "post_subtopics"])
    topic_rows = list(
        (
            await db_session.execute(
                select(Topic.name, PostTopic.confidence_score)
                .join(PostTopic, PostTopic.topic_id == Topic.id)
                .where(PostTopic.post_id == post.id)
                .order_by(PostTopic.confidence_score.desc())
            )
        ).all()
    )
    assert output.processed == 1
    assert output.failed == 0
    assert [row[0] for row in topic_rows] == [
        "AI Infrastructure",
        "Large Language Models",
        "AI Agents & Automation",
    ]
    assert [row[1] for row in topic_rows] == pytest.approx([0.96, 0.88, 0.8])
    assert post.post_subtopics == []

    prompt = batch.batch_chat.await_args.args[0][0][1]["content"]
    assert "AI Infrastructure: GPU inference" in prompt


@pytest.mark.asyncio
async def test_failed_force_classification_keeps_previous_assignment(
    db_session: AsyncSession, test_settings
) -> None:
    post = Post(
        urn="urn:li:activity:classification-preserve",
        platform="linkedin",
        content="Existing classified post",
        status="ok",
    )
    topic = Topic(name="AI Agents & Automation")
    db_session.add_all([post, topic])
    await db_session.flush()
    db_session.add(PostTopic(post_id=post.id, topic_id=topic.id, confidence_score=0.9))
    await db_session.commit()

    batch = MagicMock(spec=BatchLLMClient)
    batch.batch_chat = AsyncMock(side_effect=[[None], [None]])
    output = await ClassifyAgent(
        LLMRouter(batch, None),
        _taxonomy(),
        force=True,
        fallback_to_groq=False,
    ).run(StageContext("test", test_settings, db_session, "classify"))

    remaining = list(
        (await db_session.scalars(select(PostTopic).where(PostTopic.post_id == post.id))).all()
    )
    assert output.failed == 1
    assert len(remaining) == 1
    assert post.status == "ok"

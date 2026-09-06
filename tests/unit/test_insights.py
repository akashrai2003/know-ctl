"""Unit tests for insight parsing and vault briefing rendering."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.agents.base import StageContext
from socialgraph.agents.insight_agent import InsightAgent
from socialgraph.knowledge.insights import parse_insight
from socialgraph.knowledge.obsidian import render_post_note
from socialgraph.llm.large_client import GroqClient
from socialgraph.llm.router import LLMRouter
from socialgraph.llm.small_client import BatchLLMClient
from socialgraph.storage.models import Comment, Post


def test_parse_insight_roundtrip():
    raw = {
        "thesis": "Prefill is compute-bound; decode is memory-bound.",
        "article_takeaways": ["Disaggregation splits the two phases across GPUs."],
        "community_insights": [
            {
                "author": "Paolo Perrone",
                "claim": "Custom stacks pencil out above 50M tokens/day.",
                "why_it_matters": "Most writeups skip the build-vs-buy threshold.",
            }
        ],
        "resources": [
            {
                "title": "Turing Engine",
                "url": "https://github.com/intutic/turing",
                "value": "70B on a 24GB GPU",
            }
        ],
        "open_questions": ["Batch prefill and decode separately?"],
    }
    insight = parse_insight(raw)
    assert insight is not None
    parsed = parse_insight(insight.to_json())
    assert parsed is not None
    assert parsed.thesis.startswith("Prefill")
    assert parsed.community_insights[0].author == "Paolo Perrone"


def test_parse_insight_empty():
    assert parse_insight("") is None
    assert parse_insight("{}") is None
    assert parse_insight(None) is None


def test_parse_insight_rejects_wrong_collection_types_and_unsafe_urls():
    insight = parse_insight(
        {
            "thesis": "Grounded summary",
            "article_takeaways": "not a list",
            "community_insights": {"author": "A"},
            "resources": [{"title": "bad", "url": "javascript:alert(1)"}],
            "open_questions": 123,
        }
    )
    assert insight is not None
    assert insight.article_takeaways == []
    assert insight.community_insights == []
    assert insight.resources[0].url == ""
    assert insight.open_questions == []


@pytest.mark.asyncio
async def test_insight_agent_caches_by_evidence_hash(db_session: AsyncSession, test_settings):
    post = Post(
        urn="urn:li:activity:briefing-cache",
        platform="linkedin",
        author="Paolo Perrone",
        content="Prefill and decode have different bottlenecks.",
        status="ok",
    )
    db_session.add(post)
    await db_session.flush()
    comment = Comment(
        post_id=post.id,
        author="Paolo Perrone",
        text="A custom stack pays off above 50 million tokens per day on GPU inference.",
        kind="insight",
        usefulness_score=5.0,
    )
    db_session.add(comment)
    await db_session.commit()

    batch = MagicMock(spec=BatchLLMClient)
    groq = MagicMock(spec=GroqClient)
    groq.complete.return_value = {
        "thesis": "The serving phases need different optimization strategies.",
        "article_takeaways": [],
        "community_insights": [
            {
                "author": "Paolo",
                "claim": "Build custom infrastructure above 50M tokens/day.",
                "why_it_matters": "It provides a build-versus-buy threshold.",
            }
        ],
        "resources": [{"title": "Invented", "url": "https://invented.example"}],
        "open_questions": [],
    }
    agent = InsightAgent(LLMRouter(batch, groq))
    ctx = StageContext("test", test_settings, db_session, "insights")

    first = await agent.run(ctx)
    assert first.processed == 1
    parsed = parse_insight(post.insight_json)
    assert parsed is not None
    assert parsed.community_insights[0].author == "Paolo Perrone"
    assert parsed.resources == []
    assert post.insight_source_hash
    assert post.insight_generated_at is not None

    second = await agent.run(ctx)
    assert second.processed == 0
    assert second.meta["cached"] == 1
    assert groq.complete.call_count == 1

    comment.text += " Updated evidence."
    await db_session.commit()
    third = await agent.run(ctx)
    assert third.processed == 1
    assert groq.complete.call_count == 2


def test_post_note_uses_briefing_and_article_summary():
    content = render_post_note(
        urn="urn:li:activity:7499856654121795584",
        platform="linkedin",
        author="Hrushik Pabbathi",
        subtitle="AI Engineer",
        date_raw="5d",
        content="Original post about prefill and decode.",
        source_url="https://www.linkedin.com/feed/update/urn:li:activity:7499856654121795584/",
        topic_names=["LLM Inference"],
        external_links=[
            {
                "url": "https://example.com/inference",
                "title": "A Guide to AI Inference Engineering",
                "description": "In this article, we will walk through how inference works",
                "ai_summary": "Inference has two opposite GPU bottlenecks: prefill and decode.",
            }
        ],
        comments_notable=True,
        community=None,
        confidence="EXTRACTED",
        created_at=datetime(2026, 9, 5),
        title="Understanding LLM Inference Latency Sources\nOpposite bottlenecks",
        comments=[
            {
                "author": "Paolo Perrone",
                "text": "custom stack north of 50 million tokens a day",
                "has_external_url": False,
            }
        ],
        insight={
            "thesis": "Serving is two GPU jobs glued together.",
            "article_takeaways": ["Decode is memory-bandwidth bound."],
            "community_insights": [
                {
                    "author": "Paolo Perrone",
                    "claim": "Custom inference pencils out above 50M tokens/day.",
                    "why_it_matters": "The number most writeups skip.",
                }
            ],
            "resources": [],
            "open_questions": ["Do you batch prefill and decode separately?"],
        },
    )
    assert "## Briefing" in content
    assert "Serving is two GPU jobs glued together." in content
    assert "## From the article" in content
    assert "## Community insights" in content
    assert "50M tokens/day" in content
    assert "## Original post" in content
    assert "Original post about prefill and decode." in content
    assert "Inference has two opposite GPU bottlenecks" in content
    assert "## Thread" in content
    assert "Paolo Perrone" in content

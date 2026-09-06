"""Unit tests for comment usefulness ranking."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.agents.base import StageContext
from socialgraph.agents.comment_rank_agent import CommentRankAgent
from socialgraph.knowledge.comment_rank import (
    effective_kind,
    is_useful_comment,
    rank_comment,
    useful_comments,
)
from socialgraph.llm.router import LLMRouter
from socialgraph.llm.small_client import BatchLLMClient
from socialgraph.storage.models import Comment, Post


def test_noise_applause():
    kind, score = rank_comment("Nice one.")
    assert kind == "noise"
    assert score == 0.0
    kind, _ = rank_comment("Thanks for sharing")
    assert kind == "noise"
    kind, _ = rank_comment("Great share")
    assert kind == "noise"


def test_paolo_build_vs_buy_is_insight():
    text = (
        "a custom inference stack usually pencils out somewhere north of 50 million "
        "tokens a day, and below that the vendor's amortized R&D beats yours. "
        "that build-versus-buy threshold is the number nearly every inference writeup skips."
    )
    kind, score = rank_comment(text)
    assert kind == "insight"
    assert score >= 1.5


def test_abhishek_question():
    text = (
        "If prefill is compute-bound and decode is bandwidth-bound, the right batch "
        "size for one is wrong for the other. Do you batch them separately?"
    )
    kind, _ = rank_comment(text)
    assert kind == "question"


def test_ishan_github_is_resource():
    text = (
        "In production, decode bandwidth is where 80% of GPU time gets wasted waiting on DRAM. "
        "We found that pairing SVD INT8 KV cache compression (-75% memory traffic) "
        "https://github.com/intutic/turing"
    )
    kind, _ = rank_comment(text, has_external_url=True)
    assert kind == "resource"


def test_chat_data_promo_is_noise():
    text = (
        "If you're looking to shave off latency, https://www.chat-data.com/ can help. "
        "Their platform supports real-time model options. In short: optimize what you send."
    )
    kind, _ = rank_comment(text, has_external_url=True)
    assert kind == "noise"


def test_useful_comments_drops_noise_and_orders():
    comments = [
        SimpleNamespace(
            author="A", text="Nice one.", has_external_url=False, kind=None, usefulness_score=0
        ),
        SimpleNamespace(
            author="Paolo",
            text="custom stack north of 50 million tokens a day on GPU inference",
            has_external_url=False,
            kind=None,
            usefulness_score=0,
        ),
        SimpleNamespace(
            author="B",
            text="Thanks for sharing.",
            has_external_url=False,
            kind=None,
            usefulness_score=0,
        ),
    ]
    kept = useful_comments(comments, limit=5)
    assert len(kept) == 1
    assert kept[0].author == "Paolo"
    assert is_useful_comment(kept[0])
    assert effective_kind(comments[0]) == "noise"


@pytest.mark.asyncio
async def test_rank_agent_uses_small_model_for_ambiguous_comments(
    db_session: AsyncSession, test_settings
):
    post = Post(
        urn="urn:li:activity:ambiguous-comment",
        platform="linkedin",
        content="A post about serving models in production.",
        status="ok",
        insight_json='{"thesis":"stale"}',
    )
    db_session.add(post)
    await db_session.flush()
    comment = Comment(
        post_id=post.id,
        author="Engineer",
        text=(
            "This makes me wonder whether teams should change their deployment approach "
            "after reaching production scale."
        ),
        kind=None,
    )
    db_session.add(comment)
    await db_session.commit()

    batch = MagicMock(spec=BatchLLMClient)
    batch.batch_chat = AsyncMock(return_value=[{"kind": "question", "usefulness_score": 0.82}])
    output = await CommentRankAgent(router=LLMRouter(batch, None)).run(
        StageContext("test", test_settings, db_session, "rank_comments")
    )

    assert output.meta["llm_reviewed"] == 1
    assert comment.kind == "question"
    assert comment.usefulness_score == 8.2
    assert post.insight_json is None

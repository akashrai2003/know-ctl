"""Web service tests for briefing and community-intelligence surfaces."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.storage.models import Comment, Post
from socialgraph.web.service import get_post_detail, get_stats


@pytest.mark.asyncio
async def test_stats_and_post_detail_expose_only_high_signal_knowledge(
    db_session: AsyncSession,
):
    post = Post(
        urn="urn:li:activity:web-intelligence",
        platform="linkedin",
        author="Engineer",
        content="Original post",
        status="ok",
        insight_json=(
            '{"thesis":"A useful briefing.","article_takeaways":[],'
            '"community_insights":[],"resources":[],"open_questions":[]}'
        ),
        insight_generated_at=datetime.now(timezone.utc),
    )
    db_session.add(post)
    await db_session.flush()
    db_session.add_all(
        [
            Comment(
                post_id=post.id,
                author="Expert",
                text="Decode spends 80% of GPU time waiting on memory bandwidth.",
                kind="insight",
                usefulness_score=5.0,
            ),
            Comment(
                post_id=post.id,
                author="Fan",
                text="Nice one.",
                kind="noise",
                usefulness_score=0.0,
            ),
        ]
    )
    await db_session.commit()

    stats = await get_stats(db_session)
    detail = await get_post_detail(db_session, post.urn)

    assert stats["total_briefings"] == 1
    assert stats["briefing_coverage"] == 1.0
    assert stats["total_useful_comments"] == 1
    assert stats["useful_comments_last_7_days"] == 1
    assert detail is not None
    assert detail["insight"]["thesis"] == "A useful briefing."
    assert [comment["author"] for comment in detail["comments"]] == ["Expert"]
    assert detail["source_coverage"]["useful_comments"] == 1

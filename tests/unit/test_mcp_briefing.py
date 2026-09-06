"""Tests for the evidence-backed MCP briefing tool."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.mcp.server import TOOLS, _get_briefing
from socialgraph.storage.models import Comment, Post


def test_get_briefing_tool_is_advertised():
    assert "get_briefing" in {tool.name for tool in TOOLS}


@pytest.mark.asyncio
async def test_get_briefing_returns_structured_knowledge(db_session: AsyncSession):
    post = Post(
        urn="urn:li:activity:mcp-brief",
        platform="linkedin",
        author="Author",
        content="Post",
        status="ok",
        insight_json=(
            '{"thesis":"Decode is bandwidth bound.","article_takeaways":[],'
            '"community_insights":[],"resources":[],"open_questions":[]}'
        ),
        insight_generated_at=datetime.now(timezone.utc),
    )
    db_session.add(post)
    await db_session.flush()
    db_session.add(
        Comment(
            post_id=post.id,
            author="Engineer",
            text="The build threshold is around 50 million tokens daily.",
            kind="insight",
            usefulness_score=4.0,
        )
    )
    await db_session.commit()

    result = await _get_briefing(db_session, post.urn)
    assert result["briefing"]["thesis"] == "Decode is bandwidth bound."
    assert result["source_coverage"]["useful_comments"] == 1

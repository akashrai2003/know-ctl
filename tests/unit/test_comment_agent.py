"""Comment collection reliability tests."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.agents.base import StageContext
from socialgraph.agents.comment_agent import CommentAgent
from socialgraph.storage.models import Comment, Post


class _FakePlaywrightClient:
    result: ClassVar[dict[str, list[dict]]] = {}

    def __init__(self, _settings) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def fetch_comments_batch(self, _urns, max_per_post=80):
        assert max_per_post >= 0
        return self.result


@pytest.mark.asyncio
async def test_force_refresh_failure_preserves_comments_and_remains_retryable(
    db_session: AsyncSession, test_settings
):
    post = Post(
        urn="urn:li:activity:retry",
        platform="linkedin",
        content="Post",
        status="ok",
        comments_fetched=True,
    )
    db_session.add(post)
    await db_session.flush()
    db_session.add(Comment(post_id=post.id, author="A", text="Existing useful comment", rank=0))
    await db_session.commit()

    _FakePlaywrightClient.result = {}
    with patch("socialgraph.agents.comment_agent.PlaywrightClient", _FakePlaywrightClient):
        output = await CommentAgent(force=True, urns=[post.urn]).run(
            StageContext("test", test_settings, db_session, "comments")
        )

    stored = list(
        (await db_session.scalars(select(Comment).where(Comment.post_id == post.id))).all()
    )
    assert output.failed == 1
    assert [comment.text for comment in stored] == ["Existing useful comment"]
    assert post.comments_fetched is False


@pytest.mark.asyncio
async def test_force_refresh_replaces_comments_only_after_success(
    db_session: AsyncSession, test_settings
):
    post = Post(
        urn="urn:li:activity:replace",
        platform="linkedin",
        content="Post",
        status="ok",
        comments_fetched=True,
        insight_json='{"thesis":"stale"}',
        insight_source_hash="stale",
    )
    db_session.add(post)
    await db_session.flush()
    db_session.add(Comment(post_id=post.id, author="A", text="Old comment", rank=0))
    await db_session.commit()

    _FakePlaywrightClient.result = {
        post.urn: [
            {
                "author": "B",
                "text": "A custom inference stack pays off above 50 million tokens per day.",
                "has_external_url": False,
            }
        ]
    }
    with patch("socialgraph.agents.comment_agent.PlaywrightClient", _FakePlaywrightClient):
        output = await CommentAgent(force=True, urns=[post.urn]).run(
            StageContext("test", test_settings, db_session, "comments")
        )

    stored = list(
        (await db_session.scalars(select(Comment).where(Comment.post_id == post.id))).all()
    )
    assert output.processed == 1
    assert [comment.author for comment in stored] == ["B"]
    assert stored[0].kind is None
    assert post.comments_fetched is True
    assert post.insight_json is None
    assert post.insight_source_hash is None

"""Unit tests for Reddit connector and agents."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.agents.base import StageContext
from socialgraph.agents.comment_agent import CommentAgent
from socialgraph.agents.reddit_comment_agent import RedditCommentAgent
from socialgraph.agents.reddit_ingest_agent import RedditIngestAgent
from socialgraph.config.settings import Settings
from socialgraph.connectors.base import RawPost
from socialgraph.connectors.reddit import RedditAPIConnector
from socialgraph.storage.models import Comment, Post


def _make_reddit_settings() -> Settings:
    return Settings(
        _env_file=None,
        reddit_client_id="dummy_client_id",
        reddit_client_secret="dummy_client_secret",
        reddit_username="dummy_user",
        reddit_password="dummy_password",
    )


def test_reddit_connector_missing_credentials() -> None:
    empty_settings = Settings(_env_file=None)
    connector = RedditAPIConnector(empty_settings)
    assert not connector.is_configured()
    with pytest.raises(ValueError, match="Reddit credentials are incomplete"):
        connector._build_reddit()


@pytest.mark.asyncio
async def test_reddit_connector_fetch_saved_posts() -> None:
    import asyncpraw.models

    settings = _make_reddit_settings()
    connector = RedditAPIConnector(settings)

    # Mock submission
    mock_sub = MagicMock(spec=asyncpraw.models.Submission)
    mock_sub.name = "t3_abc123"
    mock_sub.id = "abc123"
    mock_sub.title = "Exciting AI Discovery"
    mock_sub.selftext = "Here is the post body."
    mock_sub.is_self = True
    mock_sub.permalink = "/r/MachineLearning/comments/abc123/exciting_ai_discovery/"
    mock_author = MagicMock()
    mock_author.__str__.return_value = "researcher42"
    mock_sub.author = mock_author
    mock_sub.subreddit = "MachineLearning"
    mock_sub.created_utc = 1700000000.0
    mock_sub.url = "https://reddit.com/r/MachineLearning/comments/abc123/"

    # Mock async iterator for redditor.saved()
    async def mock_saved_iter(limit=None):
        assert limit is None or limit > 0
        yield mock_sub

    mock_user = MagicMock()
    mock_user.saved = mock_saved_iter

    mock_reddit_instance = MagicMock()
    mock_reddit_instance.user.me = AsyncMock(return_value=mock_user)
    mock_reddit_instance.close = AsyncMock()

    with patch.object(connector, "_build_reddit", return_value=mock_reddit_instance):
        posts = await connector.fetch_saved_posts()

    assert len(posts) == 1
    p = posts[0]
    assert p.urn == "urn:reddit:submission:abc123"
    assert p.platform == "reddit"
    assert p.author == "researcher42"
    assert p.subtitle == "r/MachineLearning"
    assert "Exciting AI Discovery" in p.content
    assert "Here is the post body" in p.content


@pytest.mark.asyncio
async def test_reddit_ingest_agent(db_session: AsyncSession) -> None:
    settings = _make_reddit_settings()
    agent = RedditIngestAgent()

    mock_raw_posts = [
        RawPost(
            urn="urn:reddit:submission:sub1",
            platform="reddit",
            author="author1",
            subtitle="r/python",
            date_raw="2026-01-01 12:00",
            content="Title\n\nBody",
            source_url="https://reddit.com/r/python/sub1",
        )
    ]

    with patch.object(
        RedditAPIConnector, "fetch_saved_posts", new=AsyncMock(return_value=mock_raw_posts)
    ):
        ctx = StageContext(
            run_id="test-reddit-ingest", settings=settings, db=db_session, stage="ingest"
        )
        out = await agent.run(ctx)

    assert out.processed == 1
    assert out.skipped == 0

    posts = list((await db_session.scalars(select(Post).where(Post.platform == "reddit"))).all())
    assert len(posts) == 1
    assert posts[0].urn == "urn:reddit:submission:sub1"
    assert posts[0].author == "author1"


@pytest.mark.asyncio
async def test_reddit_comment_agent_isolation(db_session: AsyncSession) -> None:
    """Verify RedditCommentAgent only targets reddit posts, and CommentAgent only targets linkedin."""
    settings = _make_reddit_settings()

    # Add a LinkedIn post and a Reddit post to DB
    li_post = Post(
        urn="urn:li:activity:999",
        platform="linkedin",
        content="LinkedIn Post",
        status="ok",
        comments_fetched=False,
    )
    reddit_post = Post(
        urn="urn:reddit:submission:r123",
        platform="reddit",
        content="Reddit Post",
        status="ok",
        comments_fetched=False,
    )
    db_session.add(li_post)
    db_session.add(reddit_post)
    await db_session.commit()

    # 1. Test RedditCommentAgent — should only pick up reddit_post
    mock_reddit_comments = [
        {
            "author": "reddit_commenter",
            "text": "Great perspective here!",
            "date": "2026-01-01 13:00",
            "score": 15,
        }
    ]

    with patch.object(
        RedditAPIConnector,
        "fetch_comments_for_submission",
        new=AsyncMock(return_value=mock_reddit_comments),
    ):
        r_agent = RedditCommentAgent()
        r_ctx = StageContext(
            run_id="test-reddit-comments", settings=settings, db=db_session, stage="comments"
        )
        r_out = await r_agent.run(r_ctx)

    assert r_out.processed == 1
    await db_session.refresh(reddit_post)
    await db_session.refresh(li_post)
    assert reddit_post.comments_fetched is True
    assert li_post.comments_fetched is False

    # Check comments inserted for reddit post
    r_comments = list(
        (await db_session.scalars(select(Comment).where(Comment.post_id == reddit_post.id))).all()
    )
    assert len(r_comments) == 1
    assert r_comments[0].author == "reddit_commenter"

    # 2. Test CommentAgent (LinkedIn) — should NOT touch reddit_post
    # Since li_post has comments_fetched=False, let's verify CommentAgent only queries linkedin
    class _FakePlaywrightClient:
        def __init__(self, _settings) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def fetch_comments_batch(self, urns, max_per_post=80):
            assert max_per_post >= 0
            # Assert only LinkedIn URNs are received!
            assert all(urn.startswith("urn:li:") for urn in urns)
            return {
                "urn:li:activity:999": [
                    {"author": "linkedin_user", "text": "Insightful!", "date": "1d"}
                ]
            }

    with patch("socialgraph.agents.comment_agent.PlaywrightClient", _FakePlaywrightClient):
        li_agent = CommentAgent()
        li_ctx = StageContext(
            run_id="test-li-comments", settings=settings, db=db_session, stage="comments"
        )
        li_out = await li_agent.run(li_ctx)

    assert li_out.processed == 1
    await db_session.refresh(li_post)
    assert li_post.comments_fetched is True

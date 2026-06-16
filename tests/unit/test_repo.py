"""Unit tests for the Repo class and database operations."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.storage.enums import FetchStatus, PostStatus
from socialgraph.storage.models import PostSubtopic
from socialgraph.storage.repo import Repo


@pytest.mark.asyncio
async def test_repo_post_operations(db_session: AsyncSession) -> None:
    repo = Repo(db_session)

    # test get_or_create_post (create)
    post, created = await repo.get_or_create_post("urn:li:activity:1", "linkedin")
    assert created is True
    assert post.urn == "urn:li:activity:1"
    assert post.platform == "linkedin"
    assert post.status == PostStatus.PENDING.value

    # test get_or_create_post (get existing)
    post2, created2 = await repo.get_or_create_post("urn:li:activity:1", "linkedin")
    assert created2 is False
    assert post2.id == post.id

    # test get_posts_by_status and count_posts_by_status
    posts_pending = await repo.get_posts_by_status(PostStatus.PENDING.value)
    assert len(posts_pending) == 1
    assert posts_pending[0].urn == "urn:li:activity:1"

    counts = await repo.count_posts_by_status()
    assert counts[PostStatus.PENDING.value] == 1


@pytest.mark.asyncio
async def test_repo_topic_operations(db_session: AsyncSession) -> None:
    repo = Repo(db_session)

    # test get_or_create_topic
    topic, created = await repo.get_or_create_topic("Artificial Intelligence")
    assert created is True
    assert topic.name == "Artificial Intelligence"

    topic2, created2 = await repo.get_or_create_topic("Artificial Intelligence")
    assert created2 is False
    assert topic2.id == topic.id

    topics = await repo.get_all_topics()
    assert len(topics) == 1
    assert topics[0].name == "Artificial Intelligence"


@pytest.mark.asyncio
async def test_repo_external_link_operations(db_session: AsyncSession) -> None:
    repo = Repo(db_session)

    url = "https://example.com/some-article"
    # test get_or_create_external_link
    link, _ = await repo.get_or_create_external_link(url)
    assert link is not None
    assert link.url == url
    assert link.fetch_status == FetchStatus.PENDING.value

    # test get_pending_links
    pending = await repo.get_pending_links()
    assert len(pending) == 1
    assert pending[0].url == url


@pytest.mark.asyncio
async def test_repo_post_topic_subtopic(db_session: AsyncSession) -> None:
    repo = Repo(db_session)

    post, _ = await repo.get_or_create_post("urn:li:activity:1")
    topic, _ = await repo.get_or_create_topic("AI")

    # test upsert_post_topic
    pt = await repo.upsert_post_topic(post.id, topic.id, 0.95, "high")
    assert pt.post_id == post.id
    assert pt.topic_id == topic.id
    assert pt.confidence_score == 0.95

    # update confidence
    pt_updated = await repo.upsert_post_topic(post.id, topic.id, 0.99, "very high")
    assert pt_updated.confidence_score == 0.99

    # test upsert_post_subtopic
    ps = await repo.upsert_post_subtopic(post.id, topic.id, "LLMs")
    assert ps.subtopic_name == "LLMs"

    # update subtopic
    ps_updated = await repo.upsert_post_subtopic(post.id, topic.id, "Generative AI")
    assert ps_updated.subtopic_name == "Generative AI"

    # test rename_subtopic_in_topic
    count = await repo.rename_subtopic_in_topic("Generative AI", "Large Language Models", topic.id)
    assert count == 1

    # check if renamed
    stmt = select(PostSubtopic).where(
        PostSubtopic.post_id == post.id,
        PostSubtopic.topic_id == topic.id,
    )
    renamed_ps = await db_session.scalar(stmt)
    assert renamed_ps is not None
    assert renamed_ps.subtopic_name == "Large Language Models"


@pytest.mark.asyncio
async def test_repo_author_operations(db_session: AsyncSession) -> None:
    repo = Repo(db_session)

    # test get_or_create_author
    author, created = await repo.get_or_create_author("John Doe", "john-doe")
    assert created is True
    assert author.name == "John Doe"
    assert author.slug == "john-doe"

    author2, created2 = await repo.get_or_create_author("John Doe", "john-doe")
    assert created2 is False
    assert author2.id == author.id

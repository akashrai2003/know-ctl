"""Graph analytics: stats, co-occurrence, author profiles, timeline."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_stats(session: AsyncSession) -> dict[str, Any]:
    """Return overall counts: total posts, topics, authors, top topics, top authors."""
    from sqlalchemy import func

    from socialgraph.storage.models import Author, Post, PostTopic, Topic

    total_posts = (await session.scalar(select(func.count(Post.id)))) or 0
    total_topics = (await session.scalar(select(func.count(Topic.id)))) or 0
    total_authors = (await session.scalar(select(func.count(Author.id)))) or 0

    # Top topics by post count
    topic_counts_raw = await session.execute(
        select(Topic.name, func.count(PostTopic.id).label("cnt"))
        .join(PostTopic, PostTopic.topic_id == Topic.id)
        .group_by(Topic.id)
        .order_by(func.count(PostTopic.id).desc())
        .limit(10)
    )
    top_topics = [{"name": row[0], "count": row[1]} for row in topic_counts_raw]

    # Top authors by post count
    author_rows = await session.execute(
        select(Post.author, func.count(Post.id).label("cnt"))
        .where(Post.author.isnot(None))
        .group_by(Post.author)
        .order_by(func.count(Post.id).desc())
        .limit(10)
    )
    top_authors = [{"name": row[0], "count": row[1]} for row in author_rows]

    return {
        "total_posts": total_posts,
        "total_topics": total_topics,
        "total_authors": total_authors,
        "top_topics": top_topics,
        "top_authors": top_authors,
    }


async def get_co_occurrence(session: AsyncSession, top_n: int = 20) -> list[dict[str, Any]]:
    """Return top topic-pair co-occurrence counts."""
    from socialgraph.storage.models import PostTopic, Topic
    # Get all (post_id, topic_name) pairs
    rows = await session.execute(
        select(PostTopic.post_id, Topic.name).join(Topic, PostTopic.topic_id == Topic.id)
    )
    post_topics: dict[int, list[str]] = defaultdict(list)
    for post_id, topic_name in rows:
        post_topics[post_id].append(topic_name)

    pair_counts: Counter = Counter()
    for topics in post_topics.values():
        unique = sorted(set(topics))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                pair_counts[(unique[i], unique[j])] += 1

    return [
        {"topic_a": a, "topic_b": b, "count": c}
        for (a, b), c in pair_counts.most_common(top_n)
    ]


async def get_author_profiles(session: AsyncSession, top_n: int = 20) -> list[dict[str, Any]]:
    """Return top authors with post count and top topics."""
    from sqlalchemy import func

    from socialgraph.storage.models import Post, PostTopic, Topic

    # Posts per author
    author_rows = await session.execute(
        select(Post.author, func.count(Post.id).label("cnt"))
        .where(Post.author.isnot(None))
        .group_by(Post.author)
        .order_by(func.count(Post.id).desc())
        .limit(top_n)
    )
    authors = [(row[0], row[1]) for row in author_rows]

    results = []
    for author_name, post_count in authors:
        # Get top topics for this author
        topic_rows = await session.execute(
            select(Topic.name, func.count(PostTopic.id).label("cnt"))
            .join(PostTopic, PostTopic.topic_id == Topic.id)
            .join(Post, Post.id == PostTopic.post_id)
            .where(Post.author == author_name)
            .group_by(Topic.id)
            .order_by(func.count(PostTopic.id).desc())
            .limit(3)
        )
        top_topics = [row[0] for row in topic_rows]
        results.append({"author": author_name, "post_count": post_count, "top_topics": top_topics})

    return results


def _parse_month(date_raw: str | None) -> str | None:
    """Extract YYYY-MM from a LinkedIn date_raw string like '3mo', 'Jan 2025', etc."""
    if not date_raw:
        return None
    date_raw = date_raw.strip()
    # "Jan 2025", "Feb 2024"
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})", date_raw)
    if m:
        month_map = {
            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
            "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
            "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
        }
        return f"{m.group(2)}-{month_map[m.group(1)]}"
    # "2025-01-15" or similar ISO formats
    m2 = re.search(r"(\d{4})-(\d{2})", date_raw)
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}"
    return None


async def get_timeline(
    session: AsyncSession,
    topic: str | None = None,
    author: str | None = None,
) -> list[dict[str, Any]]:
    """Return monthly post counts, optionally filtered by topic or author."""

    from socialgraph.storage.models import Post, PostTopic, Topic

    q = select(Post.date_raw)
    if topic:
        q = (
            q.join(PostTopic, PostTopic.post_id == Post.id)
            .join(Topic, Topic.id == PostTopic.topic_id)
            .where(Topic.name == topic)
        )
    if author:
        q = q.where(Post.author == author)

    rows = await session.scalars(q)
    month_counts: Counter = Counter()
    for date_raw in rows:
        month = _parse_month(date_raw)
        if month:
            month_counts[month] += 1

    return [
        {"month": month, "count": count}
        for month, count in sorted(month_counts.items())
    ]

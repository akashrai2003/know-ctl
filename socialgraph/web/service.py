"""Service layer: all DB queries and business logic for the web API.

Keeps FastAPI route handlers thin — they just call service functions and return.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from socialgraph.config.settings import Settings
from socialgraph.knowledge.comment_rank import USEFUL_KINDS, useful_comments
from socialgraph.knowledge.insights import parse_insight
from socialgraph.storage.enums import FetchStatus
from socialgraph.storage.models import (
    Author,
    Comment,
    Embedding,
    ExternalLink,
    GraphEdge,
    PipelineRun,
    Post,
    PostExternalLink,
    PostSubtopic,
    PostTopic,
    Topic,
)
from socialgraph.storage.models import (
    GraphNode as GraphNodeModel,
)
from socialgraph.utils import slugify as _slug

logger = structlog.get_logger(__name__)


# ── Stats ─────────────────────────────────────────────────────────────────────


async def get_stats(session: AsyncSession) -> dict[str, Any]:
    """Retrieve overall counts and pipeline run status for the web dashboard.

    Args:
        session: Active SQLAlchemy database session.

    Returns:
        A dictionary containing overall metrics (posts, topics, authors, etc.)
        and the details of the last pipeline run.
    """
    total_posts = (await session.scalar(select(func.count(Post.id)))) or 0
    total_topics = (await session.scalar(select(func.count(Topic.id)))) or 0
    total_authors = (await session.scalar(select(func.count(Author.id)))) or 0
    total_embeddings = (await session.scalar(select(func.count(Embedding.id)))) or 0
    total_external_links = (await session.scalar(select(func.count(ExternalLink.id)))) or 0
    total_comments = (await session.scalar(select(func.count(Comment.id)))) or 0
    total_briefings = (
        await session.scalar(select(func.count(Post.id)).where(Post.insight_json.isnot(None)))
    ) or 0
    total_useful_comments = (
        await session.scalar(
            select(func.count(Comment.id)).where(Comment.kind.in_(tuple(USEFUL_KINDS)))
        )
    ) or 0
    week_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    useful_comments_last_7_days = (
        await session.scalar(
            select(func.count(Comment.id)).where(
                Comment.kind.in_(tuple(USEFUL_KINDS)),
                Comment.created_at >= week_cutoff,
            )
        )
    ) or 0

    # Top topics
    topic_rows = await session.execute(
        select(Topic.name, func.count(PostTopic.id).label("cnt"))
        .join(PostTopic, PostTopic.topic_id == Topic.id)
        .group_by(Topic.id)
        .order_by(func.count(PostTopic.id).desc())
        .limit(10)
    )
    top_topics = [{"name": r[0], "count": r[1]} for r in topic_rows]

    # Top authors
    author_rows = await session.execute(
        select(Post.author, func.count(Post.id).label("cnt"))
        .where(Post.author.isnot(None))
        .group_by(Post.author)
        .order_by(func.count(Post.id).desc())
        .limit(10)
    )
    top_authors = [{"name": r[0], "count": r[1]} for r in author_rows]

    # Last pipeline run
    last_run_row = await session.scalar(
        select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(1)
    )
    last_run = None
    if last_run_row:
        last_run = {
            "run_id": last_run_row.run_id,
            "status": last_run_row.status,
            "started_at": last_run_row.started_at.isoformat() if last_run_row.started_at else None,
            "completed_at": (
                last_run_row.completed_at.isoformat() if last_run_row.completed_at else None
            ),
        }

    return {
        "total_posts": total_posts,
        "total_topics": total_topics,
        "total_authors": total_authors,
        "total_embeddings": total_embeddings,
        "total_external_links": total_external_links,
        "total_comments": total_comments,
        "total_briefings": total_briefings,
        "briefing_coverage": round(total_briefings / total_posts, 4) if total_posts else 0.0,
        "total_useful_comments": total_useful_comments,
        "useful_comments_last_7_days": useful_comments_last_7_days,
        "top_topics": top_topics,
        "top_authors": top_authors,
        "last_pipeline_run": last_run,
    }


# ── Topics ────────────────────────────────────────────────────────────────────


async def list_topics(session: AsyncSession) -> list[dict]:
    """Retrieve all topics with description, post count, and slug, ordered by popularity.

    Args:
        session: Active SQLAlchemy database session.

    Returns:
        A list of topic dictionary representations.
    """
    rows = await session.execute(
        select(Topic.name, Topic.description, func.count(PostTopic.id).label("cnt"))
        .join(PostTopic, PostTopic.topic_id == Topic.id, isouter=True)
        .group_by(Topic.id)
        .order_by(func.count(PostTopic.id).desc())
    )
    return [
        {"name": r[0], "description": (r[1] or "")[:200], "post_count": r[2], "slug": _slug(r[0])}
        for r in rows
    ]


async def get_topic_detail(session: AsyncSession, slug: str) -> dict | None:
    """Fetch detailed info for a single topic, matching by slug.

    Includes associated subtopics, top authors, monthly post trends, and recent posts.

    Args:
        session: Active SQLAlchemy database session.
        slug: The unique topic URL slug.

    Returns:
        A detailed topic dictionary, or None if the topic is not found.
    """
    # Find topic by slug match
    all_topics = await session.scalars(select(Topic))
    topic = None
    for t in all_topics:
        if _slug(t.name) == slug:
            topic = t
            break
    if not topic:
        return None

    post_count = (
        await session.scalar(select(func.count(PostTopic.id)).where(PostTopic.topic_id == topic.id))
    ) or 0

    # Subtopics
    subtopic_rows = await session.scalars(
        select(PostSubtopic.subtopic_name).where(PostSubtopic.topic_id == topic.id)
    )
    subtopic_counts: Counter = Counter(subtopic_rows.all())
    subtopics = [s for s, _ in subtopic_counts.most_common(20)]

    # Top authors for this topic
    author_rows = await session.execute(
        select(Post.author, func.count(Post.id).label("cnt"))
        .join(PostTopic, PostTopic.post_id == Post.id)
        .where(PostTopic.topic_id == topic.id, Post.author.isnot(None))
        .group_by(Post.author)
        .order_by(func.count(Post.id).desc())
        .limit(10)
    )
    top_authors = [{"name": r[0], "count": r[1]} for r in author_rows]

    # Monthly trend
    from socialgraph.knowledge.graph_analytics import get_timeline

    trend = await get_timeline(session, topic=topic.name)

    # Posts (recent 50)
    post_rows = await session.scalars(
        select(Post)
        .join(PostTopic, PostTopic.post_id == Post.id)
        .where(PostTopic.topic_id == topic.id)
        .order_by(Post.created_at.desc())
        .limit(50)
    )
    posts = [
        {
            "id": p.id,
            "urn": p.urn,
            "author": p.author,
            "title": p.title,
            "date_raw": p.date_raw,
            "source_url": p.source_url,
        }
        for p in post_rows
    ]

    return {
        "name": topic.name,
        "slug": _slug(topic.name),
        "description": topic.description or "",
        "post_count": post_count,
        "subtopics": subtopics,
        "top_authors": top_authors,
        "trend": trend,
        "posts": posts,
    }


# ── Posts ─────────────────────────────────────────────────────────────────────


async def list_posts(
    session: AsyncSession,
    topic: str | None = None,
    author: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """List posts with optional filters for topic, author, or keyword search.

    Args:
        session: Active SQLAlchemy database session.
        topic: Optional topic filter name.
        author: Optional author name filter.
        q: Optional search query string for text matching.
        limit: Max number of posts to return (defaults to 20).
        offset: Offset for pagination (defaults to 0).

    Returns:
        A list of post dictionary representations.
    """
    query = (
        select(Post)
        .options(selectinload(Post.post_topics).selectinload(PostTopic.topic))
        .order_by(Post.created_at.desc())
    )
    if topic:
        query = (
            query.join(PostTopic, PostTopic.post_id == Post.id)
            .join(Topic, Topic.id == PostTopic.topic_id)
            .where(Topic.name == topic)
        )
    if author:
        query = query.where(Post.author == author)
    if q:
        pattern = f"%{q}%"
        query = query.where(Post.content.like(pattern) | Post.title.like(pattern))

    query = query.offset(offset).limit(limit)
    rows = await session.scalars(query)

    return [
        {
            "id": p.id,
            "urn": p.urn,
            "platform": p.platform,
            "author": p.author,
            "subtitle": p.subtitle,
            "date_raw": p.date_raw,
            "title": p.title,
            "summary": p.summary,
            "source_url": p.source_url,
            "topics": [pt.topic.name for pt in p.post_topics],
            "has_briefing": parse_insight(p.insight_json) is not None,
        }
        for p in rows
    ]


async def get_post_detail(
    session: AsyncSession, urn: str, _settings: Settings | None = None
) -> dict[str, Any] | None:
    """Fetch details for a single post by URN.

    Includes associated topics, external links, comments, and similar posts.

    Args:
        session: Active SQLAlchemy database session.
        urn: The unique platform URN of the post.
        _settings: Optional application settings.

    Returns:
        A detailed post dictionary, or None if not found.
    """
    post = await session.scalar(
        select(Post)
        .where(Post.urn == urn)
        .options(
            selectinload(Post.post_topics).selectinload(PostTopic.topic),
            selectinload(Post.post_links).selectinload(PostExternalLink.external_link),
            selectinload(Post.comments),
        )
    )
    if not post:
        return None

    ext_links = [
        {
            "url": pel.external_link.url,
            "title": pel.external_link.title,
            "description": pel.external_link.description,
            "ai_summary": pel.external_link.ai_summary,
        }
        for pel in post.post_links
        if pel.external_link.fetch_status == FetchStatus.OK.value
    ]

    ranked_comments = useful_comments(post.comments, limit=15)
    comments = [
        {
            "author": c.author,
            "text": c.text,
            "has_external_url": c.has_external_url,
            "kind": c.kind,
            "usefulness_score": c.usefulness_score,
        }
        for c in ranked_comments
    ]
    insight_obj = parse_insight(post.insight_json)
    insight = asdict(insight_obj) if insight_obj else None

    # Similar posts via embeddings
    similar_posts: list[dict] = []
    try:
        from socialgraph.knowledge.search import find_similar, load_embeddings

        emb_row = await session.scalar(select(Embedding).where(Embedding.post_id == post.id))
        if emb_row:
            target_vec = json.loads(emb_row.vector_json)
            all_embeddings = await load_embeddings(session)
            top = find_similar(target_vec, all_embeddings, top_k=5, exclude_post_id=post.id)
            if top:
                post_ids = [pid for pid, _ in top]
                scores = dict(top)
                rows = await session.scalars(select(Post).where(Post.id.in_(post_ids)))
                for p in rows:
                    similar_posts.append(
                        {
                            "id": p.id,
                            "urn": p.urn,
                            "author": p.author,
                            "title": p.title,
                            "score": round(scores.get(p.id, 0), 4),
                        }
                    )
                similar_posts.sort(key=lambda x: -x["score"])
    except Exception as exc:
        logger.warning("service.similar_failed", error=str(exc))

    return {
        "id": post.id,
        "urn": post.urn,
        "platform": post.platform,
        "author": post.author,
        "subtitle": post.subtitle,
        "date_raw": post.date_raw,
        "title": post.title,
        "summary": post.summary,
        "content": post.content,
        "source_url": post.source_url,
        "topics": [pt.topic.name for pt in post.post_topics],
        "external_links": ext_links,
        "comments": comments,
        "similar_posts": similar_posts,
        "insight": insight,
        "insight_generated_at": (
            post.insight_generated_at.isoformat() if post.insight_generated_at else None
        ),
        "source_coverage": {
            "articles": sum(1 for pel in post.post_links if pel.context == "body"),
            "useful_comments": len(ranked_comments),
            "comment_resources": sum(1 for pel in post.post_links if pel.context == "comment"),
        },
    }


# ── Authors ───────────────────────────────────────────────────────────────────


async def list_authors(session: AsyncSession, limit: int = 50, offset: int = 0) -> list[dict]:
    """Retrieve top authors, ordered by post count.

    Args:
        session: Active SQLAlchemy database session.
        limit: Max number of authors to return (defaults to 50).
        offset: Offset for pagination (defaults to 0).

    Returns:
        A list of author dictionary representations.
    """
    rows = await session.scalars(
        select(Author).order_by(Author.post_count.desc()).offset(offset).limit(limit)
    )
    return [
        {
            "name": a.name,
            "slug": a.slug,
            "subtitle": a.subtitle,
            "platform": a.platform,
            "post_count": a.post_count,
        }
        for a in rows
    ]


async def get_author_detail(session: AsyncSession, slug: str) -> dict | None:
    """Fetch detailed profile for a single author, matching by slug.

    Includes their top topics and recent posts.

    Args:
        session: Active SQLAlchemy database session.
        slug: The unique author URL slug.

    Returns:
        A detailed author dictionary, or None if the author is not found.
    """
    author = await session.scalar(select(Author).where(Author.slug == slug))
    if not author:
        return None

    # Top topics
    topic_rows = await session.execute(
        select(Topic.name, func.count(PostTopic.id).label("cnt"))
        .join(PostTopic, PostTopic.topic_id == Topic.id)
        .join(Post, Post.id == PostTopic.post_id)
        .where(Post.author == author.name)
        .group_by(Topic.id)
        .order_by(func.count(PostTopic.id).desc())
        .limit(5)
    )
    top_topics = [{"name": r[0], "count": r[1]} for r in topic_rows]

    # Posts
    post_rows = await session.scalars(
        select(Post).where(Post.author == author.name).order_by(Post.created_at.desc()).limit(50)
    )
    posts = [
        {
            "id": p.id,
            "urn": p.urn,
            "title": p.title,
            "date_raw": p.date_raw,
            "source_url": p.source_url,
        }
        for p in post_rows
    ]

    return {
        "name": author.name,
        "slug": author.slug,
        "subtitle": author.subtitle,
        "platform": author.platform,
        "post_count": author.post_count,
        "top_topics": top_topics,
        "posts": posts,
    }


# ── Search ────────────────────────────────────────────────────────────────────


async def semantic_search(
    session: AsyncSession,
    query: str,
    settings: Settings,
    topic: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Perform a semantic search for posts similar to the query string.

    Falls back to a keyword-like LIKE search if embeddings are not available.

    Args:
        session: Active SQLAlchemy database session.
        query: The search query text.
        settings: Application settings.
        topic: Optional topic filter name.
        limit: Max number of results to return (defaults to 20).

    Returns:
        A list of matching post dictionaries with relevance scores.
    """
    from socialgraph.knowledge.search import (
        embed_query,
        find_similar,
        keyword_search,
        load_embeddings,
    )

    all_embeddings = await load_embeddings(session)
    if all_embeddings:
        try:
            qvec = await embed_query(
                query,
                settings.vllm_base_url,
                settings.vllm_model,
                local_model_name=settings.embedding_model,
                local_device=settings.embedding_device,
            )
            filtered = all_embeddings
            if topic:
                valid_q = (
                    select(Post.id)
                    .join(PostTopic, PostTopic.post_id == Post.id)
                    .join(Topic, Topic.id == PostTopic.topic_id)
                    .where(Topic.name == topic)
                )
                valid_ids = set((await session.scalars(valid_q)).all())
                filtered = [(pid, vec) for pid, vec in all_embeddings if pid in valid_ids]

            top = find_similar(qvec, filtered, top_k=limit)
            post_ids = [pid for pid, _ in top]
            scores = dict(top)
            rows = await session.scalars(
                select(Post)
                .where(Post.id.in_(post_ids))
                .options(selectinload(Post.post_topics).selectinload(PostTopic.topic))
            )
            posts = {p.id: p for p in rows.all()}
            return [
                {
                    "id": pid,
                    "urn": posts[pid].urn,
                    "author": posts[pid].author,
                    "title": posts[pid].title,
                    "source_url": posts[pid].source_url,
                    "score": round(scores[pid], 4),
                    "topics": [pt.topic.name for pt in posts[pid].post_topics],
                }
                for pid in post_ids
                if pid in posts
            ]
        except Exception as exc:
            logger.warning("service.search_embed_failed", error=str(exc))

    # Fallback: keyword
    kw_posts = await keyword_search(session, query, limit=limit)
    return [
        {
            "id": p.id,
            "urn": p.urn,
            "author": p.author,
            "title": p.title,
            "source_url": p.source_url,
            "score": 0.0,
            "topics": [],
        }
        for p in kw_posts
    ]


# ── Graph ─────────────────────────────────────────────────────────────────────

# 19 distinct topic colors (hue-shifted for visual variety)
TOPIC_COLORS = [
    "#6366f1",
    "#8b5cf6",
    "#a855f7",
    "#d946ef",
    "#ec4899",
    "#f43f5e",
    "#ef4444",
    "#f97316",
    "#f59e0b",
    "#eab308",
    "#84cc16",
    "#22c55e",
    "#10b981",
    "#14b8a6",
    "#06b6d4",
    "#0ea5e9",
    "#3b82f6",
    "#6366f1",
    "#8b5cf6",
]


async def get_graph_data(session: AsyncSession) -> dict:
    """Build D3-compatible {nodes, links} from graph_nodes + graph_edges.

    Args:
        session: Active SQLAlchemy database session.

    Returns:
        A dictionary containing "nodes" and "links" lists for visualization.
    """
    # Load all graph nodes
    all_nodes = await session.scalars(select(GraphNodeModel))
    nodes_list = list(all_nodes.all())

    topic_nodes = [n for n in nodes_list if n.node_type == "topic"]
    post_nodes = [n for n in nodes_list if n.node_type == "post"]

    # Load edges
    all_edges = await session.scalars(select(GraphEdge))
    edges_list = list(all_edges.all())

    # Count edges per post node
    edge_count: Counter = Counter()
    for e in edges_list:
        edge_count[e.source_node_id] += 1
        edge_count[e.target_node_id] += 1

    # Top 200 most-connected post nodes
    top_post_nodes = sorted(post_nodes, key=lambda n: -edge_count.get(n.id, 0))[:200]

    # Build node ID set for filtering edges
    included_ids = {n.id for n in topic_nodes} | {n.id for n in top_post_nodes}

    # Map topic name to color
    topic_color_map = {}
    for i, tn in enumerate(sorted(topic_nodes, key=lambda n: n.label)):
        topic_color_map[tn.node_id] = TOPIC_COLORS[i % len(TOPIC_COLORS)]

    # Find which topic each post connects to (for coloring)
    post_topic_map: dict[int, str] = {}
    for e in edges_list:
        src_node = next((n for n in topic_nodes if n.id == e.source_node_id), None)
        tgt_node = next((n for n in topic_nodes if n.id == e.target_node_id), None)
        if src_node and e.target_node_id in included_ids:
            post_topic_map[e.target_node_id] = src_node.node_id
        if tgt_node and e.source_node_id in included_ids:
            post_topic_map[e.source_node_id] = tgt_node.node_id

    # Build output
    out_nodes = []
    for n in topic_nodes:
        out_nodes.append(
            {
                "id": n.node_id,
                "label": n.label,
                "type": "topic",
                "size": edge_count.get(n.id, 1),
                "color": topic_color_map.get(n.node_id, "#6366f1"),
            }
        )
    for n in top_post_nodes:
        topic_id = post_topic_map.get(n.id)
        out_nodes.append(
            {
                "id": n.node_id,
                "label": n.label[:60],
                "type": "post",
                "size": 1,
                "color": topic_color_map.get(topic_id, "#555") if topic_id else "#555",
                "topic": topic_id,
            }
        )

    # Node ID to node_id string mapping
    id_to_node_id = {n.id: n.node_id for n in nodes_list}

    out_links = []
    for e in edges_list:
        if e.source_node_id in included_ids and e.target_node_id in included_ids:
            src = id_to_node_id.get(e.source_node_id)
            tgt = id_to_node_id.get(e.target_node_id)
            if src and tgt:
                out_links.append(
                    {
                        "source": src,
                        "target": tgt,
                        "weight": e.confidence_score,
                        "relation": e.relation,
                    }
                )

    return {"nodes": out_nodes, "links": out_links}

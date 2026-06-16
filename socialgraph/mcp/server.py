"""MCP server exposing Social Graph knowledge as 8 tools.

Supports two transports:
- stdio  (for Claude Desktop / local MCP clients)
- http   (SSE transport on a given port)

Usage:
    sg mcp serve --transport stdio
    sg mcp serve --transport http --port 8765
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = structlog.get_logger(__name__)

# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS = [
    Tool(
        name="search_posts",
        description=(
            "Search saved LinkedIn posts by semantic similarity (if embeddings exist) "
            "or keyword. Optionally filter by topic name or author name."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text"},
                "topic": {"type": "string", "description": "Filter by exact topic name (optional)"},
                "author": {"type": "string", "description": "Filter by author name (optional)"},
                "limit": {"type": "integer", "default": 10, "description": "Max results"},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_topic_summary",
        description="Get a topic's description, post count, and top subtopics.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact topic name"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="get_author_profile",
        description="Get a LinkedIn author's post count and top topics.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Author name"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="find_similar",
        description="Find posts semantically similar to a given post URN.",
        inputSchema={
            "type": "object",
            "properties": {
                "urn": {"type": "string", "description": "Post URN (urn:li:activity:...)"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["urn"],
        },
    ),
    Tool(
        name="traverse_graph",
        description="BFS traversal of the topic co-occurrence graph starting from a topic.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Starting topic name"},
                "depth": {"type": "integer", "default": 2, "description": "BFS depth"},
            },
            "required": ["topic"],
        },
    ),
    Tool(
        name="get_weekly_digest",
        description="Summarize posts from the last N days grouped by topic.",
        inputSchema={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 7},
            },
        },
    ),
    Tool(
        name="list_topics",
        description="List all topics with their post counts.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_timeline",
        description="Monthly post counts, optionally filtered by topic or author.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Filter by topic name (optional)"},
                "author": {"type": "string", "description": "Filter by author name (optional)"},
            },
        },
    ),
]

# ── Server factory ────────────────────────────────────────────────────────────


def _make_server(settings) -> Server:
    server = Server("social-graph")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            result = await _dispatch(name, arguments, settings)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        except Exception as exc:
            logger.error("mcp.tool_error", tool=name, error=str(exc))
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    return server


# ── Tool dispatch ──────────────────────────────────────────────────────────────


async def _dispatch(name: str, args: dict[str, Any], settings) -> Any:
    from socialgraph.storage.db import build_session_factory, get_session

    factory = build_session_factory(settings.db_path)

    async with get_session(factory) as session:
        if name == "search_posts":
            return await _search_posts(session, settings, **args)
        elif name == "get_topic_summary":
            return await _get_topic_summary(session, **args)
        elif name == "get_author_profile":
            return await _get_author_profile(session, **args)
        elif name == "find_similar":
            return await _find_similar(session, settings, **args)
        elif name == "traverse_graph":
            return await _traverse_graph(session, **args)
        elif name == "get_weekly_digest":
            return await _get_weekly_digest(session, **args)
        elif name == "list_topics":
            return await _list_topics(session)
        elif name == "get_timeline":
            return await _get_timeline(session, **args)
        else:
            raise ValueError(f"Unknown tool: {name}")


# ── Tool implementations ───────────────────────────────────────────────────────


async def _search_posts(
    session,
    settings,
    query: str,
    topic: str | None = None,
    author: str | None = None,
    limit: int = 10,
) -> list[dict]:
    from sqlalchemy import select

    from socialgraph.knowledge.search import (
        embed_query,
        find_similar,
        keyword_search,
        load_embeddings,
    )
    from socialgraph.storage.models import Post, PostTopic, Topic

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
            # Filter by topic / author pre-similarity if requested
            if topic or author:
                valid_ids: set[int] = set()
                q = select(Post.id)
                if topic:
                    q = (
                        q.join(PostTopic, PostTopic.post_id == Post.id)
                        .join(Topic, Topic.id == PostTopic.topic_id)
                        .where(Topic.name == topic)
                    )
                if author:
                    q = q.where(Post.author == author)
                rows = await session.scalars(q)
                valid_ids = set(rows.all())
                filtered = [(pid, vec) for pid, vec in all_embeddings if pid in valid_ids]
            else:
                filtered = all_embeddings

            top = find_similar(qvec, filtered, top_k=limit)
            post_ids = [pid for pid, _ in top]
            scores = dict(top)
            rows = await session.scalars(select(Post).where(Post.id.in_(post_ids)))
            posts = {p.id: p for p in rows.all()}
            return [
                {
                    "urn": posts[pid].urn,
                    "author": posts[pid].author,
                    "title": posts[pid].title,
                    "score": round(scores[pid], 4),
                    "source_url": posts[pid].source_url,
                }
                for pid in post_ids
                if pid in posts
            ]
        except Exception as exc:
            logger.warning("mcp.search_embed_failed", error=str(exc))

    # Fallback: keyword search
    kw_posts = await keyword_search(session, query, limit=limit)
    return [
        {"urn": p.urn, "author": p.author, "title": p.title, "source_url": p.source_url}
        for p in kw_posts
    ]


async def _get_topic_summary(session, name: str) -> dict:
    from collections import Counter

    from sqlalchemy import func, select

    from socialgraph.storage.models import PostSubtopic, PostTopic, Topic

    topic = await session.scalar(select(Topic).where(Topic.name == name))
    if not topic:
        return {"error": f"Topic '{name}' not found"}

    post_count = (
        await session.scalar(select(func.count(PostTopic.id)).where(PostTopic.topic_id == topic.id))
    ) or 0

    subtopic_rows = await session.scalars(
        select(PostSubtopic.subtopic_name).where(PostSubtopic.topic_id == topic.id)
    )
    subtopic_counts: Counter = Counter(subtopic_rows.all())
    top_subtopics = [s for s, _ in subtopic_counts.most_common(5)]

    return {
        "name": topic.name,
        "description": topic.description or "",
        "post_count": post_count,
        "top_subtopics": top_subtopics,
    }


async def _get_author_profile(session, name: str) -> dict:
    from sqlalchemy import func, select

    from socialgraph.storage.models import Post, PostTopic, Topic

    post_count = (await session.scalar(select(func.count(Post.id)).where(Post.author == name))) or 0
    if post_count == 0:
        return {"error": f"Author '{name}' not found"}

    topic_rows = await session.execute(
        select(Topic.name, func.count(PostTopic.id).label("cnt"))
        .join(PostTopic, PostTopic.topic_id == Topic.id)
        .join(Post, Post.id == PostTopic.post_id)
        .where(Post.author == name)
        .group_by(Topic.id)
        .order_by(func.count(PostTopic.id).desc())
        .limit(5)
    )
    top_topics = [row[0] for row in topic_rows]

    return {"author": name, "post_count": post_count, "top_topics": top_topics}


async def _find_similar(session, _settings, urn: str, limit: int = 5) -> list[dict]:
    from sqlalchemy import select

    from socialgraph.knowledge.search import find_similar, load_embeddings
    from socialgraph.storage.models import Embedding, Post

    post = await session.scalar(select(Post).where(Post.urn == urn))
    if not post:
        return [{"error": f"Post URN {urn} not found"}]

    emb_row = await session.scalar(select(Embedding).where(Embedding.post_id == post.id))
    if not emb_row:
        return [{"error": "No embedding for this post. Run sg embed first."}]

    import json as _json

    target_vec = _json.loads(emb_row.vector_json)
    all_embeddings = await load_embeddings(session)

    top = find_similar(target_vec, all_embeddings, top_k=limit, exclude_post_id=post.id)
    post_ids = [pid for pid, _ in top]
    scores = dict(top)
    rows = await session.scalars(select(Post).where(Post.id.in_(post_ids)))
    posts = {p.id: p for p in rows.all()}
    return [
        {
            "urn": posts[pid].urn,
            "author": posts[pid].author,
            "title": posts[pid].title,
            "score": round(scores[pid], 4),
        }
        for pid in post_ids
        if pid in posts
    ]


async def _traverse_graph(session, topic: str, depth: int = 2) -> dict:
    from socialgraph.knowledge.graph_analytics import get_co_occurrence

    all_pairs = await get_co_occurrence(session, top_n=200)
    # Build adjacency from co-occurrence pairs
    adj: dict[str, list[str]] = {}
    for pair in all_pairs:
        a, b = pair["topic_a"], pair["topic_b"]
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    # BFS
    visited: dict[str, int] = {topic: 0}
    queue = [topic]
    while queue:
        current = queue.pop(0)
        current_depth = visited[current]
        if current_depth >= depth:
            continue
        for neighbor in adj.get(current, []):
            if neighbor not in visited:
                visited[neighbor] = current_depth + 1
                queue.append(neighbor)

    return {
        "start": topic,
        "depth": depth,
        "nodes": [{"topic": t, "depth": d} for t, d in sorted(visited.items(), key=lambda x: x[1])],
    }


async def _get_weekly_digest(session, days: int = 7) -> dict:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from socialgraph.storage.models import Post, PostTopic, Topic

    # Parse all posts; LinkedIn date_raw is relative so we use created_at as proxy
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await session.execute(
        select(Post.urn, Post.author, Post.title, Post.content, Topic.name.label("topic"))
        .join(PostTopic, PostTopic.post_id == Post.id, isouter=True)
        .join(Topic, Topic.id == PostTopic.topic_id, isouter=True)
        .where(Post.created_at >= cutoff)
        .order_by(Post.created_at.desc())
    )
    by_topic: dict[str, list[dict]] = {}
    seen_urns: set[str] = set()
    for row in rows:
        urn, author, title, content, topic_name = row
        if urn in seen_urns:
            continue
        seen_urns.add(urn)
        key = topic_name or "Uncategorized"
        by_topic.setdefault(key, []).append(
            {
                "urn": urn,
                "author": author,
                "title": title or (content or "")[:80],
            }
        )

    return {
        "days": days,
        "total_posts": len(seen_urns),
        "by_topic": dict(sorted(by_topic.items())),
    }


async def _list_topics(session) -> list[dict]:
    from sqlalchemy import func, select

    from socialgraph.storage.models import PostTopic, Topic

    rows = await session.execute(
        select(Topic.name, Topic.description, func.count(PostTopic.id).label("cnt"))
        .join(PostTopic, PostTopic.topic_id == Topic.id, isouter=True)
        .group_by(Topic.id)
        .order_by(func.count(PostTopic.id).desc())
    )
    return [
        {"name": row[0], "description": (row[1] or "")[:200], "post_count": row[2]} for row in rows
    ]


async def _get_timeline(
    session,
    topic: str | None = None,
    author: str | None = None,
) -> list[dict]:
    from socialgraph.knowledge.graph_analytics import get_timeline

    return await get_timeline(session, topic=topic, author=author)


# ── Entry points ──────────────────────────────────────────────────────────────


async def run_stdio(settings) -> None:
    """Run MCP server over stdio (for Claude Desktop integration)."""
    server = _make_server(settings)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def run_sse(settings, port: int = 8765) -> None:
    """Run MCP server over SSE/HTTP."""
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    server = _make_server(settings)
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )
    logger.info("mcp.server_start", transport="http", port=port)
    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    await srv.serve()

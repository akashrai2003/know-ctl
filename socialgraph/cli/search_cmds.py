"""Search CLI commands for social-graph."""

from __future__ import annotations

from typing import Any

import typer

from socialgraph.cli._runner import run_async


def search(
    query: str = typer.Argument(..., help="Search query"),
    topic: str | None = typer.Option(None, "--topic", help="Filter by topic"),
    author: str | None = typer.Option(None, "--author", help="Filter by author"),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    """Semantic search over saved posts."""
    from sqlalchemy import select

    from socialgraph.knowledge.search import (
        embed_query,
        find_similar,
        keyword_search,
        load_embeddings,
    )
    from socialgraph.storage.models import Post, PostTopic, Topic

    async def _run(settings: Any, session: Any) -> None:
        all_embeddings = await load_embeddings(session)
        posts: list = []

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
                if topic or author:
                    q = select(Post.id)
                    if topic:
                        q = (
                            q.join(PostTopic, PostTopic.post_id == Post.id)
                            .join(Topic, Topic.id == PostTopic.topic_id)
                            .where(Topic.name == topic)
                        )
                    if author:
                        q = q.where(Post.author == author)
                    valid_ids = set((await session.scalars(q)).all())
                    filtered = [(pid, vec) for pid, vec in all_embeddings if pid in valid_ids]

                top = find_similar(qvec, filtered, top_k=limit)
                post_ids = [pid for pid, _ in top]
                scores = dict(top)
                rows = await session.scalars(select(Post).where(Post.id.in_(post_ids)))
                for p in rows.all():
                    posts.append((p, scores.get(p.id, 0.0)))
            except Exception as exc:
                typer.echo(f"Embedding search failed ({exc}), falling back to keyword search")

        if not posts:
            kw_posts = await keyword_search(session, query, limit=limit)
            posts = [(p, 0.0) for p in kw_posts]

        typer.echo(f"Results for: {query!r}\n")
        for p, score in posts:
            score_str = f" [{score:.3f}]" if score else ""
            typer.echo(f"  {p.author or 'Unknown'}{score_str}: {p.title or p.content[:80]}")
            if p.source_url:
                typer.echo(f"    {p.source_url}")

    run_async(_run)


def similar(
    urn: str = typer.Argument(..., help="Post URN to find similar posts for"),
    limit: int = typer.Option(5, "--limit", "-n"),
) -> None:
    """Find posts semantically similar to a given post URN."""
    import json as _json

    from sqlalchemy import select

    from socialgraph.knowledge.search import find_similar, load_embeddings
    from socialgraph.storage.models import Embedding, Post

    async def _run(_settings: Any, session: Any) -> None:
        post = await session.scalar(select(Post).where(Post.urn == urn))
        if not post:
            typer.echo(f"Post not found: {urn}", err=True)
            raise typer.Exit(1)
        emb_row = await session.scalar(select(Embedding).where(Embedding.post_id == post.id))
        if not emb_row:
            typer.echo("No embedding for this post. Run `sg embed` first.", err=True)
            raise typer.Exit(1)
        target_vec = _json.loads(emb_row.vector_json)
        all_embeddings = await load_embeddings(session)
        top = find_similar(target_vec, all_embeddings, top_k=limit, exclude_post_id=post.id)
        post_ids = [pid for pid, _ in top]
        scores = dict(top)
        rows = await session.scalars(select(Post).where(Post.id.in_(post_ids)))
        results = sorted(rows.all(), key=lambda p: -scores.get(p.id, 0.0))
        typer.echo(f"Similar to: {post.title or post.urn}\n")
        for p in results:
            typer.echo(
                f"  [{scores[p.id]:.3f}] {p.author or 'Unknown'}: {p.title or p.content[:80]}"
            )

    run_async(_run)

"""Graph analytics CLI commands for social-graph."""

from __future__ import annotations

from typing import Any

import typer

from socialgraph.cli._runner import run_async

graph_app = typer.Typer(help="Graph analytics commands")


@graph_app.command("stats")
def graph_stats() -> None:
    """Show overall knowledge graph statistics."""
    from socialgraph.knowledge.graph_analytics import get_stats

    async def _run(_settings: Any, session: Any) -> None:
        stats = await get_stats(session)
        typer.echo(f"Total posts:   {stats['total_posts']}")
        typer.echo(f"Total topics:  {stats['total_topics']}")
        typer.echo(f"Total authors: {stats['total_authors']}")
        typer.echo("\nTop topics:")
        for t in stats["top_topics"]:
            typer.echo(f"  {t['name']}: {t['count']} posts")
        typer.echo("\nTop authors:")
        for a in stats["top_authors"]:
            typer.echo(f"  {a['name']}: {a['count']} posts")

    run_async(_run)


@graph_app.command("co-occurrence")
def graph_co_occurrence(
    top: int = typer.Option(20, "--top", "-n", help="Number of pairs to show"),
) -> None:
    """Show top topic co-occurrence pairs."""
    from socialgraph.knowledge.graph_analytics import get_co_occurrence

    async def _run(_settings: Any, session: Any) -> None:
        pairs = await get_co_occurrence(session, top_n=top)
        typer.echo("Topic co-occurrence:\n")
        for p in pairs:
            typer.echo(f"  {p['topic_a']} × {p['topic_b']}: {p['count']}")

    run_async(_run)


@graph_app.command("authors")
def graph_authors(
    top: int = typer.Option(20, "--top", "-n"),
) -> None:
    """Show top authors with post counts and topics."""
    from socialgraph.knowledge.graph_analytics import get_author_profiles

    async def _run(_settings: Any, session: Any) -> None:
        profiles = await get_author_profiles(session, top_n=top)
        typer.echo("Top authors:\n")
        for p in profiles:
            topics = ", ".join(p["top_topics"]) if p["top_topics"] else "—"
            typer.echo(f"  {p['author']} ({p['post_count']} posts) — {topics}")

    run_async(_run)


@graph_app.command("timeline")
def graph_timeline(
    topic: str | None = typer.Option(None, "--topic", help="Filter by topic"),
    author: str | None = typer.Option(None, "--author", help="Filter by author"),
) -> None:
    """Show monthly post counts (optionally filtered)."""
    from socialgraph.knowledge.graph_analytics import get_timeline

    async def _run(_settings: Any, session: Any) -> None:
        rows = await get_timeline(session, topic=topic, author=author)
        label = f" (topic={topic})" if topic else ""
        label += f" (author={author})" if author else ""
        typer.echo(f"Monthly post counts{label}:\n")
        for row in rows:
            bar = "█" * min(row["count"], 40)
            typer.echo(f"  {row['month']}  {bar}  {row['count']}")

    run_async(_run)

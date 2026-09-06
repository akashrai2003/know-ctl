"""Typer CLI for social-graph."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
import typer

from socialgraph.cli import pipeline_cmds, schedule_cmds, search_cmds, server_cmds
from socialgraph.cli.graph_cmds import graph_app

app = typer.Typer(name="sg", help="Social Graph — LinkedIn posts to Obsidian knowledge graph")

_log = structlog.get_logger("cli")


def _get_settings():
    from socialgraph.config.settings import Settings

    return Settings()


def _configure_logging(settings) -> None:
    from socialgraph.logging import configure_logging

    settings.ensure_workspace()
    configure_logging(settings)


def _get_taxonomy(settings):
    from socialgraph.knowledge.taxonomy import Taxonomy

    if settings.taxonomy_path.exists():
        return Taxonomy.from_file(settings.taxonomy_path)
    typer.echo(
        f"Taxonomy not found at {settings.taxonomy_path}. Run `make bootstrap-taxonomy` first.",
        err=True,
    )
    raise typer.Exit(1)


@app.command()
def init() -> None:
    """Initialize workspace directories and database."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.storage.db import create_all_tables

    asyncio.run(create_all_tables(settings.db_path))
    typer.echo(f"Initialized: {settings.workspace_dir} and {settings.obsidian_vault_path}")


@app.command()
def status() -> None:
    """Show pipeline status (post counts per stage) and scheduler status."""
    settings = _get_settings()
    _configure_logging(settings)
    from sqlalchemy import func, select

    from socialgraph.runner.scheduler import SchedulerDaemon
    from socialgraph.storage.db import build_session_factory, get_session
    from socialgraph.storage.models import Comment, Post
    from socialgraph.storage.repo import Repo

    async def _status():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            repo = Repo(session)
            counts = await repo.count_posts_by_status()
            briefings = (
                await session.scalar(
                    select(func.count(Post.id)).where(Post.insight_json.isnot(None))
                )
            ) or 0
            useful_comments = (
                await session.scalar(
                    select(func.count(Comment.id)).where(
                        Comment.kind.in_(("insight", "question", "resource"))
                    )
                )
            ) or 0
            comments_pending = (
                await session.scalar(
                    select(func.count(Post.id)).where(Post.comments_fetched == False)  # noqa: E712
                )
            ) or 0
        total = sum(counts.values())
        typer.echo(f"Total posts: {total}")
        for status_val, count in sorted(counts.items()):
            typer.echo(f"  {status_val}: {count}")

        typer.echo("\nKnowledge intelligence:")
        typer.echo(f"  AI briefings:       {briefings}/{total}")
        typer.echo(f"  Useful comments:    {useful_comments}")
        typer.echo(f"  Threads to collect: {comments_pending}")

        sched_status = SchedulerDaemon.read_status(settings)
        typer.echo("\n📋 Scheduler:")
        if sched_status:
            typer.echo("  Status:       RUNNING")
            typer.echo(f"  PID:          {sched_status.get('pid', '—')}")
            typer.echo(f"  Interval:     {sched_status.get('interval_hours', '—')}h")
            typer.echo(f"  Last run:     {sched_status.get('last_run', '—')}")
            typer.echo(f"  Next run:     {sched_status.get('next_run', '—')}")
            typer.echo(f"  Last result:  {sched_status.get('last_result', '—')}")
            typer.echo(f"  Posts added:  {sched_status.get('posts_processed', '—')}")
        else:
            typer.echo("  Status:       STOPPED")

    asyncio.run(_status())


@app.command()
def run(
    start_from: str | None = typer.Option(None, "--from", help="Start from this stage"),
    only: str | None = typer.Option(None, "--stage", help="Run only this stage"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without changes"),
    json_file: Path = typer.Option(
        Path("linkedin_saved_posts.json"), "--json", help="JSON file for ingest stage"
    ),
    live: bool = typer.Option(
        False, "--live", help="Force live scraping via Playwright instead of JSON"
    ),
    headless: bool = typer.Option(
        True,
        "--headless/--no-headless",
        help="Run browser headless (no window) when running live. Default: headless.",
    ),
) -> None:
    """Run the complete pipeline (ingest → comments → rank → enrich → classify → insights → vault)."""
    settings = _get_settings()
    _configure_logging(settings)

    runs_ingest = only == "ingest" or (
        only is None and (start_from is None or start_from == "ingest")
    )
    if runs_ingest and not live and not json_file.exists():
        typer.echo(
            f"⚠️ JSON file '{json_file}' not found. Falling back to live scraping...", err=True
        )
        live = True

    if live:
        settings.playwright_headless = headless

    taxonomy = _get_taxonomy(settings) if not dry_run else None

    from socialgraph.llm.factory import build_router

    router = build_router(settings) if not dry_run else None

    from socialgraph.agents.classify_agent import ClassifyAgent
    from socialgraph.agents.comment_agent import CommentAgent
    from socialgraph.agents.comment_enrich_agent import CommentEnrichAgent
    from socialgraph.agents.comment_rank_agent import CommentRankAgent
    from socialgraph.agents.embed_agent import EmbedAgent
    from socialgraph.agents.enrich_agent import EnrichAgent
    from socialgraph.agents.graph_build_agent import GraphBuildAgent
    from socialgraph.agents.ingest_agent import IngestAgent
    from socialgraph.agents.insight_agent import InsightAgent
    from socialgraph.agents.semantic_edge_agent import SemanticEdgeAgent
    from socialgraph.agents.subtopic_agent import SubtopicAgent
    from socialgraph.agents.vault_write_agent import VaultWriteAgent
    from socialgraph.pipeline.orchestrator import PipelineOrchestrator
    from socialgraph.storage.db import build_session_factory

    factory = build_session_factory(settings.db_path)
    from socialgraph.agents.base import Agent

    agents: dict[str, Agent] = {
        "ingest": IngestAgent(json_path=json_file if not live else None, live_mode=live),
        "comments": CommentAgent(max_per_post=settings.max_comments),
        "rank_comments": CommentRankAgent(router=router),
        "embed": EmbedAgent(batch_size=settings.batch_size),
        "semantic_edges": SemanticEdgeAgent(),
        "graph_build": GraphBuildAgent(),
        "vault_write": VaultWriteAgent(),
    }
    if router:
        agents["comment_enrich"] = CommentEnrichAgent(router=router)
        agents["enrich"] = EnrichAgent(router=router)
        agents["subtopic"] = SubtopicAgent(router=router)
        agents["insights"] = InsightAgent(router=router)
        if taxonomy:
            agents["classify"] = ClassifyAgent(router, taxonomy)
    orchestrator = PipelineOrchestrator(agents=agents, settings=settings, session_factory=factory)

    async def _run():
        result = await orchestrator.run(start_from=start_from, only_stage=only, dry_run=dry_run)
        typer.echo(f"Pipeline run {result.run_id}: {result.status}")
        for stage_out in result.stages:
            typer.echo(
                f"  {stage_out.stage}: processed={stage_out.processed} "
                f"skipped={stage_out.skipped} failed={stage_out.failed}"
            )

    asyncio.run(_run())


# Register modularized command subfiles on `app`
app.command(name="ingest")(pipeline_cmds.ingest)
app.command(name="scrape")(pipeline_cmds.scrape)
app.command(name="enrich")(pipeline_cmds.enrich)
app.command(name="classify")(pipeline_cmds.classify)
app.command(name="build-graph")(pipeline_cmds.build_graph)
app.command(name="vault-write")(pipeline_cmds.vault_write)
app.command(name="subtopic")(pipeline_cmds.subtopic)
app.command(name="comment-enrich")(pipeline_cmds.comment_enrich)
app.command(name="comments")(pipeline_cmds.comments)
app.command(name="rank-comments")(pipeline_cmds.rank_comments)
app.command(name="insights")(pipeline_cmds.insights)
app.command(name="brief")(pipeline_cmds.brief)
app.command(name="embed")(pipeline_cmds.embed)
app.command(name="semantic-edges")(pipeline_cmds.semantic_edges)

app.command(name="search")(search_cmds.search)
app.command(name="similar")(search_cmds.similar)

app.command(name="mcp-serve")(server_cmds.mcp_serve)
app.command(name="web")(server_cmds.web)

app.add_typer(graph_app, name="graph")

# Schedule commands sub-app
schedule_app = typer.Typer(
    name="schedule", help="Background scheduler for incremental pipeline runs"
)
schedule_app.command(name="start")(schedule_cmds.schedule_start)
schedule_app.command(name="stop")(schedule_cmds.schedule_stop)
schedule_app.command(name="status")(schedule_cmds.schedule_status)
app.add_typer(schedule_app)

if __name__ == "__main__":
    app()

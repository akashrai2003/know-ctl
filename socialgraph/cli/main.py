"""Typer CLI for social-graph."""
from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
import typer

app = typer.Typer(name="sg", help="Social Graph — LinkedIn posts to Obsidian knowledge graph")

_log = structlog.get_logger("cli")


def _get_settings():
    from socialgraph.config.settings import Settings
    return Settings()


def _configure_logging(settings) -> None:
    from socialgraph.logging import configure_logging
    settings.ensure_workspace()
    configure_logging(settings)


def _get_router(settings):
    from socialgraph.llm.large_client import GroqClient
    from socialgraph.llm.router import LLMRouter
    from socialgraph.llm.small_client import BatchLLMClient
    batch = BatchLLMClient(
        batch_url=settings.vllm_batch_url,
        model=settings.vllm_model,
        timeout=settings.llm_timeout,
    )
    groq = GroqClient(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        base_url=settings.groq_base_url,
        fallback_models=settings.groq_fallback_models,
    )
    return LLMRouter(batch, groq)


def _get_taxonomy(settings):
    from socialgraph.knowledge.taxonomy import Taxonomy
    if settings.taxonomy_path.exists():
        return Taxonomy.from_file(settings.taxonomy_path)
    typer.echo(f"Taxonomy not found at {settings.taxonomy_path}. Run `make bootstrap-taxonomy` first.", err=True)
    raise typer.Exit(1)


@app.command()
def init():
    """Initialize workspace directories and database."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.storage.db import create_all_tables
    asyncio.run(create_all_tables(settings.db_path))
    typer.echo(f"Initialized: {settings.workspace_dir} and {settings.obsidian_vault_path}")


@app.command()
def status():
    """Show pipeline status (post counts per stage)."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.storage.db import build_session_factory, get_session
    from socialgraph.storage.repo import Repo

    async def _status():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            repo = Repo(session)
            counts = await repo.count_posts_by_status()
        total = sum(counts.values())
        typer.echo(f"Total posts: {total}")
        for status_val, count in sorted(counts.items()):
            typer.echo(f"  {status_val}: {count}")

    asyncio.run(_status())


@app.command()
def ingest(
    json_file: Path = typer.Option(
        Path("linkedin_saved_posts.json"), "--json", "-j", help="Path to linkedin_saved_posts.json"
    ),
):
    """Ingest posts from the LinkedIn JSON export."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.ingest_agent import IngestAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            agent = IngestAgent(json_file)
            ctx = StageContext(run_id="cli-ingest", settings=settings, db=session, stage="ingest")
            out = await agent.run(ctx)
        typer.echo(f"Ingest done: {out.processed} new, {out.skipped} skipped")

    asyncio.run(_run())


@app.command()
def scrape(
    headless: bool = typer.Option(
        False,
        "--headless/--no-headless",
        help="Run browser headless (no window). Default: visible so you can handle 2FA.",
    ),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Save extracted posts to a timestamped JSON backup."),
):
    """Log into LinkedIn via Playwright, extract saved posts, and ingest them into the DB.

    The browser opens visibly by default so you can handle 2FA/CAPTCHA if LinkedIn asks.
    Once posts are extracted they are saved to a timestamped backup JSON file, then ingested.
    """
    import json
    from datetime import datetime

    settings = _get_settings()
    _configure_logging(settings)

    # Override headless for this command
    settings.playwright_headless = headless

    from socialgraph.agents.base import StageContext
    from socialgraph.connectors.linkedin import LinkedInPlaywrightConnector
    from socialgraph.storage.db import build_session_factory, get_session
    from socialgraph.storage.repo import Repo

    typer.echo("Opening browser — log into LinkedIn if prompted, then wait...")

    async def _run():
        connector = LinkedInPlaywrightConnector(settings)
        raw_posts = await connector.fetch_saved_posts()

        if not raw_posts:
            typer.echo("No posts extracted. Check browser output above.", err=True)
            raise typer.Exit(1)

        typer.echo(f"Extracted {len(raw_posts)} posts from LinkedIn.")

        if backup:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = Path(f"linkedin_saved_posts_{ts}.json")
            backup_data = [
                {
                    "urn": p.urn,
                    "author": p.author,
                    "subtitle": p.subtitle,
                    "date": p.date_raw,
                    "content": p.content,
                    "source_url": p.source_url,
                }
                for p in raw_posts
            ]
            backup_path.write_text(json.dumps(backup_data, indent=2, ensure_ascii=False), encoding="utf-8")
            typer.echo(f"Backup saved to {backup_path}")

        factory = build_session_factory(settings.db_path)
        processed = skipped = 0
        async with get_session(factory) as session:
            repo = Repo(session)
            for rp in raw_posts:
                post, created = await repo.get_or_create_post(rp.urn, rp.platform)
                if not created:
                    # For reposts: update content if the new version is richer
                    # (hydration combined original content — old DB entry had only the commentary)
                    old_len = len(post.content or "")
                    new_len = len(rp.content or "")
                    if new_len > old_len + 20:
                        post.author = rp.author
                        post.content = rp.content
                        post.source_url = rp.source_url
                        processed += 1
                    else:
                        skipped += 1
                    continue
                post.author = rp.author
                post.subtitle = rp.subtitle
                post.date_raw = rp.date_raw
                post.content = rp.content
                post.source_url = rp.source_url
                post.status = "ingested"
                processed += 1
            await session.commit()

        typer.echo(f"Ingest done: {processed} new, {skipped} already in DB")

    asyncio.run(_run())


@app.command()
def enrich():
    """Enrich all ingested posts (fetch external URLs)."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.enrich_agent import EnrichAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            agent = EnrichAgent()
            ctx = StageContext(run_id="cli-enrich", settings=settings, db=session, stage="enrich")
            out = await agent.run(ctx)
        typer.echo(f"Enrich done: {out.processed} enriched, {out.failed} failed")

    asyncio.run(_run())


@app.command()
def classify():
    """Classify enriched posts into topics."""
    settings = _get_settings()
    _configure_logging(settings)
    taxonomy = _get_taxonomy(settings)
    router = _get_router(settings)
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.classify_agent import ClassifyAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            agent = ClassifyAgent(router, taxonomy)
            ctx = StageContext(run_id="cli-classify", settings=settings, db=session, stage="classify")
            out = await agent.run(ctx)
        typer.echo(f"Classify done: {out.processed} classified, {out.failed} failed")

    asyncio.run(_run())


@app.command(name="build-graph")
def build_graph():
    """Build the knowledge graph from classified posts."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.graph_build_agent import GraphBuildAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            agent = GraphBuildAgent()
            ctx = StageContext(run_id="cli-graph", settings=settings, db=session, stage="graph_build")
            out = await agent.run(ctx)
        typer.echo(f"Graph build done: {out.processed} nodes")

    asyncio.run(_run())


@app.command(name="vault-write")
def vault_write():
    """Write Obsidian vault from graph data."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.vault_write_agent import VaultWriteAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            agent = VaultWriteAgent()
            ctx = StageContext(run_id="cli-vault", settings=settings, db=session, stage="vault_write")
            out = await agent.run(ctx)
        typer.echo(f"Vault write done: {out.processed} notes, {out.failed} failed")

    asyncio.run(_run())


@app.command()
def subtopic(
    force: bool = typer.Option(False, "--force", help="Re-generate titles/subtopics even if already set"),
):
    """Generate LLM titles and subtopics for all classified posts."""
    settings = _get_settings()
    _configure_logging(settings)
    router = _get_router(settings)
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.subtopic_agent import SubtopicAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            agent = SubtopicAgent(router)
            ctx = StageContext(run_id="cli-subtopic", settings=settings, db=session, stage="subtopic")
            out = await agent.run(ctx)
        typer.echo(f"Subtopic done: {out.processed} processed, {out.failed} failed")

    asyncio.run(_run())


@app.command()
def run(
    start_from: str | None = typer.Option(None, "--from", help="Start from this stage"),
    only: str | None = typer.Option(None, "--stage", help="Run only this stage"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without changes"),
    json_file: Path = typer.Option(
        Path("linkedin_saved_posts.json"), "--json", help="JSON file for ingest stage"
    ),
):
    """Run the full pipeline (ingest → enrich → classify → graph_build → vault_write)."""
    settings = _get_settings()
    _configure_logging(settings)
    taxonomy = _get_taxonomy(settings) if not dry_run else None
    router = _get_router(settings) if not dry_run else None
    from socialgraph.agents.classify_agent import ClassifyAgent
    from socialgraph.agents.enrich_agent import EnrichAgent
    from socialgraph.agents.graph_build_agent import GraphBuildAgent
    from socialgraph.agents.ingest_agent import IngestAgent
    from socialgraph.agents.vault_write_agent import VaultWriteAgent
    from socialgraph.pipeline.orchestrator import PipelineOrchestrator
    from socialgraph.storage.db import build_session_factory

    factory = build_session_factory(settings.db_path)
    agents = {
        "ingest": IngestAgent(json_file),
        "enrich": EnrichAgent(),
        "classify": ClassifyAgent(router, taxonomy) if router and taxonomy else None,
        "graph_build": GraphBuildAgent(),
        "vault_write": VaultWriteAgent(),
    }
    agents = {k: v for k, v in agents.items() if v is not None}
    orchestrator = PipelineOrchestrator(agents=agents, settings=settings, session_factory=factory)

    async def _run():
        result = await orchestrator.run(
            start_from=start_from, only_stage=only, dry_run=dry_run
        )
        typer.echo(f"Pipeline run {result.run_id}: {result.status}")
        for stage_out in result.stages:
            typer.echo(
                f"  {stage_out.stage}: processed={stage_out.processed} "
                f"skipped={stage_out.skipped} failed={stage_out.failed}"
            )

    asyncio.run(_run())

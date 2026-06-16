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
    groq = None
    if settings.groq_api_key:
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
    """Show pipeline status (post counts per stage) and scheduler status."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.runner.scheduler import SchedulerDaemon
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
def ingest(
    json_file: Path = typer.Option(
        Path("linkedin_saved_posts.json"), "--json", "-j", help="Path to linkedin_saved_posts.json"
    ),
    live: bool = typer.Option(False, "--live", help="Scrape LinkedIn live using Playwright connector"),
    headless: bool = typer.Option(
        True,
        "--headless/--no-headless",
        help="Run browser headless (no window) when running live. Default: headless.",
    ),
):
    """Ingest posts from the LinkedIn JSON export or live scraping."""
    settings = _get_settings()
    _configure_logging(settings)
    if live:
        settings.playwright_headless = headless
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.ingest_agent import IngestAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            agent = IngestAgent(json_path=json_file if not live else None, live_mode=live)
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
    """Enrich all posts (fetch external URLs, then summarize with vLLM)."""
    settings = _get_settings()
    _configure_logging(settings)
    router = _get_router(settings)
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.enrich_agent import EnrichAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            agent = EnrichAgent(router=router)
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


@app.command(name="comment-enrich")
def comment_enrich(
    limit: int = typer.Option(0, "--limit", "-n", help="Max comments to process (0 = all)"),
    summarize_only: bool = typer.Option(False, "--summarize-only", help="Skip fetching; re-run LLM summarization on already-fetched comment links"),
):
    """Fetch and LLM-summarize external URLs found in post comments."""
    settings = _get_settings()
    _configure_logging(settings)
    router = _get_router(settings)
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.comment_enrich_agent import CommentEnrichAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            agent = CommentEnrichAgent(router=router, limit=limit)
            ctx = StageContext(
                run_id="cli-comment-enrich",
                settings=settings,
                db=session,
                stage="comment_enrich",
            )
            out = await agent.run(ctx, summarize_only=summarize_only)
        typer.echo(
            f"Comment-enrich done: {out.processed} comments, "
            f"{out.failed} failed, "
            f"{out.meta.get('summary_candidates', out.meta.get('summarized', 0))} links summarized"
        )

    asyncio.run(_run())


@app.command()
def run(
    start_from: str | None = typer.Option(None, "--from", help="Start from this stage"),
    only: str | None = typer.Option(None, "--stage", help="Run only this stage"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without changes"),
    json_file: Path = typer.Option(
        Path("linkedin_saved_posts.json"), "--json", help="JSON file for ingest stage"
    ),
    live: bool = typer.Option(False, "--live", help="Force live scraping via Playwright instead of JSON"),
    headless: bool = typer.Option(
        True,
        "--headless/--no-headless",
        help="Run browser headless (no window) when running live. Default: headless.",
    ),
):
    """Run the complete pipeline (ingest → comments → comment_enrich → enrich → classify → embed → subtopic → semantic_edges → graph_build → vault_write)."""
    settings = _get_settings()
    _configure_logging(settings)

    if not live and not json_file.exists():
        typer.echo(f"⚠️ JSON file '{json_file}' not found. Falling back to live scraping...", err=True)
        live = True

    if live:
        settings.playwright_headless = headless

    taxonomy = _get_taxonomy(settings) if not dry_run else None
    router = _get_router(settings) if not dry_run else None

    from socialgraph.agents.classify_agent import ClassifyAgent
    from socialgraph.agents.comment_agent import CommentAgent
    from socialgraph.agents.comment_enrich_agent import CommentEnrichAgent
    from socialgraph.agents.embed_agent import EmbedAgent
    from socialgraph.agents.enrich_agent import EnrichAgent
    from socialgraph.agents.graph_build_agent import GraphBuildAgent
    from socialgraph.agents.ingest_agent import IngestAgent
    from socialgraph.agents.semantic_edge_agent import SemanticEdgeAgent
    from socialgraph.agents.subtopic_agent import SubtopicAgent
    from socialgraph.agents.vault_write_agent import VaultWriteAgent
    from socialgraph.pipeline.orchestrator import PipelineOrchestrator
    from socialgraph.storage.db import build_session_factory

    factory = build_session_factory(settings.db_path)
    agents = {
        "ingest": IngestAgent(json_path=json_file if not live else None, live_mode=live),
        "comments": CommentAgent(max_per_post=settings.max_comments),
        "comment_enrich": CommentEnrichAgent(router=router) if router else None,
        "enrich": EnrichAgent(router=router) if router else None,
        "classify": ClassifyAgent(router, taxonomy) if router and taxonomy else None,
        "embed": EmbedAgent(batch_size=settings.batch_size),
        "subtopic": SubtopicAgent(router=router) if router else None,
        "semantic_edges": SemanticEdgeAgent(),
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


# ── New M1-M5 commands ────────────────────────────────────────────────────────

@app.command()
def comments(
    limit: int = typer.Option(0, "--limit", "-n", help="Max posts to fetch comments for (0 = all)"),
    force: bool = typer.Option(False, "--force", help="Re-fetch even if already fetched"),
    max_per_post: int = typer.Option(-1, "--max-per-post", help="Max comments to fetch per post (-1 = use SG_MAX_COMMENTS from env)"),
    headless: bool = typer.Option(True, "--headless/--no-headless"),
):
    """Scrape LinkedIn comments for saved posts via Voyager API (paginates through 'Load more')."""
    settings = _get_settings()
    _configure_logging(settings)
    settings.playwright_headless = headless
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.comment_agent import CommentAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            effective_max = max_per_post if max_per_post >= 0 else settings.max_comments
            agent = CommentAgent(limit=limit, force=force, max_per_post=effective_max)
            ctx = StageContext(run_id="cli-comments", settings=settings, db=session, stage="comments")
            out = await agent.run(ctx)
        typer.echo(
            f"Comments done: {out.processed} posts, "
            f"{out.meta.get('total_comments', 0)} comments fetched"
        )

    asyncio.run(_run())


@app.command()
def embed(
    batch_size: int = typer.Option(32, "--batch-size", help="Posts per embedding API call"),
):
    """Generate vLLM embeddings for all posts and store them in the DB."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.embed_agent import EmbedAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            agent = EmbedAgent(batch_size=batch_size)
            ctx = StageContext(run_id="cli-embed", settings=settings, db=session, stage="embed")
            out = await agent.run(ctx)
        typer.echo(f"Embed done: {out.processed} embedded, {out.failed} failed")

    asyncio.run(_run())


@app.command(name="semantic-edges")
def semantic_edges(
    threshold: float = typer.Option(0.85, "--threshold", help="Cosine similarity threshold"),
):
    """Create GraphEdge rows for post pairs with high embedding similarity."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.semantic_edge_agent import SemanticEdgeAgent
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            agent = SemanticEdgeAgent(threshold=threshold)
            ctx = StageContext(run_id="cli-semantic-edges", settings=settings, db=session, stage="semantic_edges")
            out = await agent.run(ctx)
        typer.echo(f"Semantic edges done: {out.processed} edges created")

    asyncio.run(_run())



@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    topic: str | None = typer.Option(None, "--topic", help="Filter by topic"),
    author: str | None = typer.Option(None, "--author", help="Filter by author"),
    limit: int = typer.Option(10, "--limit", "-n"),
):
    """Semantic search over saved posts."""
    settings = _get_settings()
    _configure_logging(settings)
    from sqlalchemy import select

    from socialgraph.knowledge.search import (
        embed_query,
        find_similar,
        keyword_search,
        load_embeddings,
    )
    from socialgraph.storage.db import build_session_factory, get_session
    from socialgraph.storage.models import Post, PostTopic, Topic

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
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
                    scores = {pid: sc for pid, sc in top}
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

    asyncio.run(_run())


@app.command()
def similar(
    urn: str = typer.Argument(..., help="Post URN to find similar posts for"),
    limit: int = typer.Option(5, "--limit", "-n"),
):
    """Find posts semantically similar to a given post URN."""
    settings = _get_settings()
    _configure_logging(settings)
    import json as _json

    from sqlalchemy import select

    from socialgraph.knowledge.search import find_similar, load_embeddings
    from socialgraph.storage.db import build_session_factory, get_session
    from socialgraph.storage.models import Embedding, Post

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
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
            scores = {pid: sc for pid, sc in top}
            rows = await session.scalars(select(Post).where(Post.id.in_(post_ids)))
            results = sorted(rows.all(), key=lambda p: -scores.get(p.id, 0.0))
        typer.echo(f"Similar to: {post.title or post.urn}\n")
        for p in results:
            typer.echo(f"  [{scores[p.id]:.3f}] {p.author or 'Unknown'}: {p.title or p.content[:80]}")

    asyncio.run(_run())


# ── sg graph subcommands ──────────────────────────────────────────────────────

graph_app = typer.Typer(help="Graph analytics commands")
app.add_typer(graph_app, name="graph")


@graph_app.command("stats")
def graph_stats():
    """Show overall knowledge graph statistics."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.knowledge.graph_analytics import get_stats
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
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

    asyncio.run(_run())


@graph_app.command("co-occurrence")
def graph_co_occurrence(
    top: int = typer.Option(20, "--top", "-n", help="Number of pairs to show"),
):
    """Show top topic co-occurrence pairs."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.knowledge.graph_analytics import get_co_occurrence
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            pairs = await get_co_occurrence(session, top_n=top)
        typer.echo("Topic co-occurrence:\n")
        for p in pairs:
            typer.echo(f"  {p['topic_a']} × {p['topic_b']}: {p['count']}")

    asyncio.run(_run())


@graph_app.command("authors")
def graph_authors(
    top: int = typer.Option(20, "--top", "-n"),
):
    """Show top authors with post counts and topics."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.knowledge.graph_analytics import get_author_profiles
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            profiles = await get_author_profiles(session, top_n=top)
        typer.echo("Top authors:\n")
        for p in profiles:
            topics = ", ".join(p["top_topics"]) if p["top_topics"] else "—"
            typer.echo(f"  {p['author']} ({p['post_count']} posts) — {topics}")

    asyncio.run(_run())


@graph_app.command("timeline")
def graph_timeline(
    topic: str | None = typer.Option(None, "--topic", help="Filter by topic"),
    author: str | None = typer.Option(None, "--author", help="Filter by author"),
):
    """Show monthly post counts (optionally filtered)."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.knowledge.graph_analytics import get_timeline
    from socialgraph.storage.db import build_session_factory, get_session

    async def _run():
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            rows = await get_timeline(session, topic=topic, author=author)
        label = f" (topic={topic})" if topic else ""
        label += f" (author={author})" if author else ""
        typer.echo(f"Monthly post counts{label}:\n")
        for row in rows:
            bar = "█" * min(row["count"], 40)
            typer.echo(f"  {row['month']}  {bar}  {row['count']}")

    asyncio.run(_run())


# ── sg mcp-serve ──────────────────────────────────────────────────────────────

@app.command(name="mcp-serve")
def mcp_serve(
    transport: str = typer.Option("stdio", "--transport", help="Transport: stdio or http"),
    port: int = typer.Option(8765, "--port", help="Port for HTTP transport"),
):
    """Start the MCP server (stdio for Claude Desktop, http for web clients)."""
    settings = _get_settings()
    _configure_logging(settings)
    from socialgraph.mcp.server import run_sse, run_stdio

    if transport == "stdio":
        typer.echo("Starting MCP server (stdio)...", err=True)
        asyncio.run(run_stdio(settings))
    elif transport == "http":
        typer.echo(f"Starting MCP server (HTTP/SSE) on port {port}...", err=True)
        asyncio.run(run_sse(settings, port=port))
    else:
        typer.echo(f"Unknown transport: {transport}. Use stdio or http.", err=True)
        raise typer.Exit(1)


# ── sg web ────────────────────────────────────────────────────────────────────

@app.command(name="web")
def web(
    port: int = typer.Option(8080, "--port", help="Port to run web server on"),
    host: str = typer.Option("0.0.0.0", "--host", help="Host to bind to"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser on start"),
):
    """Start the web dashboard (REST API + frontend)."""
    settings = _get_settings()
    _configure_logging(settings)

    import uvicorn

    from socialgraph.web.main import create_app

    app_instance = create_app(settings)

    if open_browser:
        import threading
        import time
        import webbrowser

        def _open():
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{port}")

        threading.Thread(target=_open, daemon=True).start()

    typer.echo(f"🌐 Starting Social Graph dashboard on http://localhost:{port}")
    uvicorn.run(app_instance, host=host, port=port, log_level="warning")


# ── sg schedule ───────────────────────────────────────────────────────────────

schedule_app = typer.Typer(name="schedule", help="Background scheduler for incremental pipeline runs")
app.add_typer(schedule_app)


@schedule_app.command(name="start")
def schedule_start(
    interval_hours: float = typer.Option(
        None, "--interval-hours", help="Run interval in hours (default: SG_SCHEDULE_INTERVAL_HOURS or 6)"
    ),
):
    """Start the background scheduler daemon."""
    settings = _get_settings()
    _configure_logging(settings)
    hours = interval_hours or settings.schedule_interval_hours
    from socialgraph.runner.scheduler import SchedulerDaemon

    daemon = SchedulerDaemon(settings)
    typer.echo(f"⏱️  Starting scheduler — pipeline runs every {hours:.1f} hours")
    typer.echo("Press Ctrl+C to stop")
    try:
        daemon.start(hours)
    except KeyboardInterrupt:
        daemon.stop()
        typer.echo("\n🛑 Scheduler stopped")


@schedule_app.command(name="stop")
def schedule_stop():
    """Stop the background scheduler (by removing PID from schedule.json)."""
    from socialgraph.runner.scheduler import SchedulerDaemon

    settings = _get_settings()
    _configure_logging(settings)
    status = SchedulerDaemon.read_status(settings)
    if not status or not status.get("pid"):
        typer.echo("No scheduler is currently running.")
        raise typer.Exit(0)
    import os
    import signal

    pid = status["pid"]
    try:
        os.kill(pid, signal.SIGTERM)
        typer.echo(f"🛑 Sent SIGTERM to scheduler (PID {pid})")
    except ProcessLookupError:
        typer.echo(f"Scheduler (PID {pid}) is not running — cleaning up status")
    SchedulerDaemon.clear_status(settings)


@schedule_app.command(name="status")
def schedule_status():
    """Show current scheduler status."""
    from socialgraph.runner.scheduler import SchedulerDaemon

    settings = _get_settings()
    status = SchedulerDaemon.read_status(settings)
    if not status:
        typer.echo("📋 Scheduler: not running (no schedule.json)")
        return

    typer.echo("📋 Scheduler Status:")
    typer.echo(f"   PID:          {status.get('pid', '—')}")
    typer.echo(f"   Interval:     {status.get('interval_hours', '—')}h")
    typer.echo(f"   Last run:     {status.get('last_run', '—')}")
    typer.echo(f"   Next run:     {status.get('next_run', '—')}")
    typer.echo(f"   Last result:  {status.get('last_result', '—')}")
    typer.echo(f"   Posts added:  {status.get('posts_processed', '—')}")


"""Pipeline CLI commands for social-graph."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from socialgraph.cli._runner import get_taxonomy, run_async
from socialgraph.llm.factory import build_router


def ingest(
    json_file: Path = typer.Option(
        Path("linkedin_saved_posts.json"), "--json", "-j", help="Path to linkedin_saved_posts.json"
    ),
    live: bool = typer.Option(
        False, "--live", help="Scrape LinkedIn live using Playwright connector"
    ),
    headless: bool = typer.Option(
        True,
        "--headless/--no-headless",
        help="Run browser headless (no window) when running live. Default: headless.",
    ),
) -> None:
    """Ingest posts from the LinkedIn JSON export or live scraping."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.ingest_agent import IngestAgent

    async def _run(settings: Any, session: Any) -> None:
        agent = IngestAgent(json_path=json_file if not live else None, live_mode=live)
        ctx = StageContext(run_id="cli-ingest", settings=settings, db=session, stage="ingest")
        out = await agent.run(ctx)
        typer.echo(f"Ingest done: {out.processed} new, {out.skipped} skipped")

    run_async(_run, playwright_headless=headless)


def scrape(
    headless: bool = typer.Option(
        False,
        "--headless/--no-headless",
        help="Run browser headless (no window). Default: visible so you can handle 2FA.",
    ),
    backup: bool = typer.Option(
        True, "--backup/--no-backup", help="Save extracted posts to a timestamped JSON backup."
    ),
) -> None:
    """Log into LinkedIn via Playwright, extract saved posts, and ingest them into the DB.

    The browser opens visibly by default so you can handle 2FA/CAPTCHA if LinkedIn asks.
    Once posts are extracted they are saved to a timestamped backup JSON file, then ingested.
    """
    from socialgraph.connectors.linkedin import LinkedInPlaywrightConnector
    from socialgraph.storage.repo import Repo

    typer.echo("Opening browser — log into LinkedIn if prompted, then wait...")

    async def _run(settings: Any, session: Any) -> None:
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
            backup_path.write_text(
                json.dumps(backup_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            typer.echo(f"Backup saved to {backup_path}")

            processed = skipped = 0
            repo = Repo(session)
            for rp in raw_posts:
                post, created = await repo.get_or_create_post(rp.urn, rp.platform)
                if not created:
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
                from socialgraph.storage.enums import PostStatus

                post.status = PostStatus.INGESTED.value
                processed += 1
            await session.commit()

        typer.echo(f"Ingest done: {processed} added/updated, {skipped} unchanged in DB")

    run_async(_run, playwright_headless=headless)


def enrich() -> None:
    """Enrich all posts (fetch external URLs, then summarize with vLLM)."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.enrich_agent import EnrichAgent

    async def _run(settings: Any, session: Any) -> None:
        router = build_router(settings)
        agent = EnrichAgent(router=router)
        ctx = StageContext(run_id="cli-enrich", settings=settings, db=session, stage="enrich")
        out = await agent.run(ctx)
        typer.echo(f"Enrich done: {out.processed} enriched, {out.failed} failed")

    run_async(_run)


def classify() -> None:
    """Classify enriched posts into topics."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.classify_agent import ClassifyAgent

    async def _run(settings: Any, session: Any) -> None:
        taxonomy = get_taxonomy(settings)
        router = build_router(settings)
        agent = ClassifyAgent(router, taxonomy)
        ctx = StageContext(run_id="cli-classify", settings=settings, db=session, stage="classify")
        out = await agent.run(ctx)
        typer.echo(f"Classify done: {out.processed} classified, {out.failed} failed")

    run_async(_run)


def build_graph() -> None:
    """Build the knowledge graph from classified posts."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.graph_build_agent import GraphBuildAgent

    async def _run(settings: Any, session: Any) -> None:
        agent = GraphBuildAgent()
        ctx = StageContext(run_id="cli-graph", settings=settings, db=session, stage="graph_build")
        out = await agent.run(ctx)
        typer.echo(f"Graph build done: {out.processed} nodes")

    run_async(_run)


def vault_write() -> None:
    """Write Obsidian vault from graph data."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.vault_write_agent import VaultWriteAgent

    async def _run(settings: Any, session: Any) -> None:
        agent = VaultWriteAgent()
        ctx = StageContext(run_id="cli-vault", settings=settings, db=session, stage="vault_write")
        out = await agent.run(ctx)
        typer.echo(f"Vault write done: {out.processed} notes, {out.failed} failed")

    run_async(_run)


def subtopic(
    _force: bool = typer.Option(
        False, "--force", help="Re-generate titles/subtopics even if already set"
    ),
) -> None:
    """Generate LLM titles and subtopics for all classified posts."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.subtopic_agent import SubtopicAgent

    async def _run(settings: Any, session: Any) -> None:
        router = build_router(settings)
        agent = SubtopicAgent(router)
        ctx = StageContext(run_id="cli-subtopic", settings=settings, db=session, stage="subtopic")
        out = await agent.run(ctx)
        typer.echo(f"Subtopic done: {out.processed} processed, {out.failed} failed")

    run_async(_run)


def comment_enrich(
    limit: int = typer.Option(0, "--limit", "-n", help="Max comments to process (0 = all)"),
    summarize_only: bool = typer.Option(
        False,
        "--summarize-only",
        help="Skip fetching; re-run LLM summarization on already-fetched comment links",
    ),
) -> None:
    """Fetch and LLM-summarize external URLs found in post comments."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.comment_enrich_agent import CommentEnrichAgent

    async def _run(settings: Any, session: Any) -> None:
        router = build_router(settings)
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

    run_async(_run)


def comments(
    limit: int = typer.Option(0, "--limit", "-n", help="Max posts to fetch comments for (0 = all)"),
    force: bool = typer.Option(False, "--force", help="Re-fetch even if already fetched"),
    max_per_post: int = typer.Option(
        -1,
        "--max-per-post",
        help="Max comments to fetch per post (-1 = use SG_MAX_COMMENTS from env)",
    ),
    urn: str | None = typer.Option(None, "--urn", help="Fetch comments for a single post URN"),
    headless: bool = typer.Option(True, "--headless/--no-headless"),
) -> None:
    """Scrape LinkedIn comments. Fetch generously; usefulness ranking happens after."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.comment_agent import CommentAgent

    async def _run(settings: Any, session: Any) -> None:
        effective_max = max_per_post if max_per_post >= 0 else settings.max_comments
        agent = CommentAgent(
            limit=limit,
            force=force,
            max_per_post=effective_max,
            urns=[urn] if urn else None,
        )
        ctx = StageContext(run_id="cli-comments", settings=settings, db=session, stage="comments")
        out = await agent.run(ctx)
        typer.echo(
            f"Comments done: {out.processed} posts, "
            f"{out.meta.get('total_comments', 0)} comments fetched"
        )

    run_async(_run, playwright_headless=headless)


def rank_comments() -> None:
    """Score stored comments and mark applause/promo as noise."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.comment_rank_agent import CommentRankAgent

    async def _run(settings: Any, session: Any) -> None:
        has_provider = bool(
            settings.vllm_base_url or settings.vllm_batch_url or settings.groq_api_key
        )
        agent = CommentRankAgent(router=build_router(settings) if has_provider else None)
        ctx = StageContext(
            run_id="cli-rank-comments", settings=settings, db=session, stage="rank_comments"
        )
        out = await agent.run(ctx)
        typer.echo(
            f"Rank comments done: {out.processed} ranked, "
            f"useful={out.meta.get('useful', 0)} noise={out.meta.get('noise', 0)}"
        )

    run_async(_run)


def insights(
    limit: int = typer.Option(0, "--limit", "-n", help="Max posts to brief (0 = all missing)"),
    urn: str | None = typer.Option(None, "--urn", help="Brief a single post URN"),
    force: bool = typer.Option(False, "--force", help="Regenerate even if insight_json exists"),
    provider: str = typer.Option(
        "auto", "--provider", help="Briefing model provider: auto, groq, or local."
    ),
    local_model: str | None = typer.Option(
        None,
        "--local-model",
        help="Override SG_VLLM_MODEL for this run (the model must be loaded by the server).",
    ),
) -> None:
    """Generate AI briefings from post + article + useful comments."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.insight_agent import InsightAgent

    async def _run(settings: Any, session: Any) -> None:
        router = build_router(settings)
        agent = InsightAgent(
            router=router,
            limit=limit,
            force=force,
            urns=[urn] if urn else None,
            provider=provider,
        )
        ctx = StageContext(run_id="cli-insights", settings=settings, db=session, stage="insights")
        out = await agent.run(ctx)
        typer.echo(f"Insights done: {out.processed} briefed, {out.failed} failed")

    run_async(_run, vllm_model=local_model)


def brief(
    urn: str = typer.Argument(..., help="Post URN to brief and rewrite in the vault"),
    fetch_comments: bool = typer.Option(
        False, "--fetch-comments", help="Scrape comments for this URN before briefing"
    ),
    headless: bool = typer.Option(True, "--headless/--no-headless"),
) -> None:
    """End-to-end briefing for one post: optional comment fetch → Groq insight → vault note."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.comment_agent import CommentAgent
    from socialgraph.agents.comment_rank_agent import CommentRankAgent
    from socialgraph.agents.insight_agent import InsightAgent
    from socialgraph.agents.vault_write_agent import VaultWriteAgent

    async def _run(settings: Any, session: Any) -> None:
        ctx_kwargs = {"settings": settings, "db": session}
        router = build_router(settings)
        if fetch_comments:
            comments_agent = CommentAgent(
                force=True, max_per_post=settings.max_comments, urns=[urn]
            )
            out = await comments_agent.run(
                StageContext(run_id="cli-brief-comments", stage="comments", **ctx_kwargs)
            )
            typer.echo(
                f"Comments: {out.processed} posts, {out.meta.get('total_comments', 0)} fetched"
            )

        rank_out = await CommentRankAgent(router=router, urns=[urn]).run(
            StageContext(run_id="cli-brief-rank", stage="rank_comments", **ctx_kwargs)
        )
        typer.echo(f"Ranked: {rank_out.processed}")

        insight_out = await InsightAgent(router=router, force=True, urns=[urn]).run(
            StageContext(run_id="cli-brief-insights", stage="insights", **ctx_kwargs)
        )
        typer.echo(f"Insight: {insight_out.processed} briefed, {insight_out.failed} failed")
        if insight_out.processed != 1:
            typer.echo(
                "Could not generate the requested briefing. Check the URN, Groq configuration, "
                "and logs.",
                err=True,
            )
            raise typer.Exit(1)

        vault_out = await VaultWriteAgent(urns=[urn], rebuild_collections=False).run(
            StageContext(run_id="cli-brief-vault", stage="vault_write", **ctx_kwargs)
        )
        typer.echo(f"Vault: {vault_out.processed} notes")

    run_async(_run, playwright_headless=headless if fetch_comments else None)


def embed(
    batch_size: int = typer.Option(32, "--batch-size", help="Posts per embedding API call"),
) -> None:
    """Generate vLLM embeddings for all posts and store them in the DB."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.embed_agent import EmbedAgent

    async def _run(settings: Any, session: Any) -> None:
        agent = EmbedAgent(batch_size=batch_size)
        ctx = StageContext(run_id="cli-embed", settings=settings, db=session, stage="embed")
        out = await agent.run(ctx)
        typer.echo(f"Embed done: {out.processed} embedded, {out.failed} failed")

    run_async(_run)


def semantic_edges(
    threshold: float = typer.Option(0.85, "--threshold", help="Cosine similarity threshold"),
) -> None:
    """Create GraphEdge rows for post pairs with high embedding similarity."""
    from socialgraph.agents.base import StageContext
    from socialgraph.agents.semantic_edge_agent import SemanticEdgeAgent

    async def _run(settings: Any, session: Any) -> None:
        agent = SemanticEdgeAgent(threshold=threshold)
        ctx = StageContext(
            run_id="cli-semantic-edges", settings=settings, db=session, stage="semantic_edges"
        )
        out = await agent.run(ctx)
        typer.echo(f"Semantic edges done: {out.processed} edges created, {out.failed} failed")

    run_async(_run)

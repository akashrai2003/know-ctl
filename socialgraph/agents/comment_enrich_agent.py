"""CommentEnrichAgent — fetch and LLM-summarize URLs found in LinkedIn comments.

For every comment that (a) has_external_url=True and (b) urls_enriched=False the
agent:
  1. Extracts URLs from the comment text.
  2. Fetches each URL (reusing the shared fetch helpers from enrich_agent).
  3. Creates/reuses an ExternalLink record.
  4. Creates a PostExternalLink(context="comment", comment_id=…) row so the
     vault writer can show comment-sourced links separately.
  5. After all HTTP work is done, runs one LLM batch pass that generates
     ai_summary values for every newly-fetched link, using the comment text
     as context for a richer, more targeted summary.
  6. Marks the comment as urls_enriched=True.

Run with:
    sg comment-enrich
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog
from playwright.async_api import Browser, async_playwright
from sqlalchemy import or_, select, update

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.agents.enrich_agent import (
    FETCH_TIMEOUT,
    PW_CONCURRENCY,
    _extract_urls,
    _resolve_and_fetch,
    should_fetch_url,
)
from socialgraph.storage.enums import FetchStatus
from socialgraph.storage.models import Comment, ExternalLink, Post, PostExternalLink
from socialgraph.storage.repo import Repo

if TYPE_CHECKING:
    from socialgraph.llm.router import LLMRouter

logger = structlog.get_logger(__name__)

CONCURRENCY = 8  # simultaneous HTTP fetches


class CommentEnrichAgent:
    """Fetch and LLM-summarize external URLs mentioned in post comments."""

    name = "comment_enrich"

    def __init__(self, router: LLMRouter | None = None, limit: int = 0) -> None:
        self._router = router
        self._limit = limit

    async def run(self, ctx: StageContext, summarize_only: bool = False) -> StageOutput:
        if summarize_only:
            return await self._run_summarize_only(ctx)

        # ── 1. Load unprocessed comments that mention a URL ──────────────
        q = select(Comment).where(
            Comment.has_external_url == True,  # noqa: E712
            Comment.urls_enriched == False,  # noqa: E712
            or_(Comment.kind.is_(None), Comment.kind != "noise"),
        )
        if self._limit:
            q = q.limit(self._limit)

        result = await ctx.db.scalars(q)
        comments: list[Comment] = list(result.all())

        if not comments:
            logger.info("comment_enrich.skip", reason="no unprocessed comments with URLs")
            return StageOutput(
                stage=self.name, skipped=1, meta={"reason": "no comments to process"}
            )

        logger.info("comment_enrich.start", count=len(comments))

        repo = Repo(ctx.db)
        semaphore = asyncio.Semaphore(CONCURRENCY)
        db_sem = asyncio.Semaphore(1)
        processed = failed = 0

        # Track (external_link_id, comment) pairs for the LLM pass
        # Only newly-fetched links (no ai_summary yet) are queued here.
        needs_summary: list[tuple[int, Comment]] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            pw_sem = asyncio.Semaphore(PW_CONCURRENCY)

            async with httpx.AsyncClient(
                timeout=FETCH_TIMEOUT,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    )
                },
                follow_redirects=True,
            ) as client:

                async def enrich_comment(comment: Comment) -> None:
                    nonlocal processed, failed
                    async with semaphore:
                        try:
                            link_ids = await _process_comment(
                                comment, repo, client, browser, pw_sem, db_sem
                            )
                            needs_summary.extend((lid, comment) for lid in link_ids)
                            processed += 1
                        except Exception as exc:
                            logger.error(
                                "comment_enrich.comment_failed",
                                comment_id=comment.id,
                                error=str(exc),
                            )
                            failed += 1

                await asyncio.gather(*[enrich_comment(c) for c in comments])

            await browser.close()

        await ctx.db.commit()

        # ── 2. LLM summarization pass (comment-aware) ────────────────────
        if self._router and needs_summary:
            log_path = Path(ctx.settings.workspace_dir) / "logs" / "comment_summarization.jsonl"
            await _summarize_comment_links(ctx.db, self._router, needs_summary, log_path)

        # New resources and summaries change the evidence used by a post briefing.
        # Invalidate only successfully processed posts; InsightAgent will rebuild them.
        affected_post_ids = {comment.post_id for comment in comments if comment.urls_enriched}
        if affected_post_ids:
            await ctx.db.execute(
                update(Post)
                .where(Post.id.in_(affected_post_ids))
                .values(
                    insight_json=None,
                    insight_source_hash=None,
                    insight_generated_at=None,
                )
            )
        await ctx.db.commit()

        logger.info("comment_enrich.complete", processed=processed, failed=failed)
        return StageOutput(
            stage=self.name,
            processed=processed,
            failed=failed,
            meta={"summary_candidates": len(needs_summary)},
        )

    async def _run_summarize_only(self, ctx: StageContext) -> StageOutput:
        """Re-run only the LLM summarization pass over already-fetched comment links.

        Queries PostExternalLink(context="comment") rows whose ExternalLink has
        body_excerpt but no ai_summary, reconstructs the comment context from
        comment_id, then calls _summarize_comment_links.
        """
        from sqlalchemy.orm import selectinload

        if not self._router:
            logger.warning("comment_enrich.summarize_only_skip", reason="no LLM router")
            return StageOutput(stage=self.name, skipped=1, meta={"reason": "no router"})

        result = await ctx.db.scalars(
            select(PostExternalLink)
            .where(PostExternalLink.context == "comment")
            .options(
                selectinload(PostExternalLink.external_link),
            )
        )
        pels = list(result.all())

        # Build (link_id, Comment) pairs — load comment for context
        needs_summary: list[tuple[int, Comment]] = []
        seen_link_ids: set[int] = set()
        for pel in pels:
            lnk = pel.external_link
            if not lnk or lnk.fetch_status != "ok" or not lnk.body_excerpt:
                continue
            if lnk.ai_summary is not None:
                continue
            if lnk.id in seen_link_ids:
                continue
            seen_link_ids.add(lnk.id)
            comment: Comment | None = None
            if pel.comment_id:
                comment = await ctx.db.get(Comment, pel.comment_id)
            if comment is None:
                # Fallback: create a minimal stand-in so summarization still runs
                comment = Comment(author=None, text="")
            needs_summary.append((lnk.id, comment))

        if not needs_summary:
            logger.info("comment_enrich.summarize_only_skip", reason="all links already summarized")
            return StageOutput(stage=self.name, skipped=1, meta={"reason": "nothing to summarize"})

        logger.info("comment_enrich.summarize_only_start", count=len(needs_summary))
        log_path = Path(ctx.settings.workspace_dir) / "logs" / "comment_summarization.jsonl"
        await _summarize_comment_links(ctx.db, self._router, needs_summary, log_path)
        await ctx.db.commit()
        return StageOutput(
            stage=self.name,
            processed=len(needs_summary),
            meta={"summarized": len(needs_summary)},
        )


async def _process_comment(
    comment: Comment,
    repo: Repo,
    client: httpx.AsyncClient,
    browser: Browser,
    pw_sem: asyncio.Semaphore,
    db_sem: asyncio.Semaphore,
) -> list[int]:
    """Extract, fetch, and record all URLs from a single comment.

    Returns a list of external_link_id values for links that were newly fetched
    and may need LLM summarization.
    """
    urls = _extract_urls(comment.text or "")
    new_link_ids: list[int] = []

    for url in urls:
        if not should_fetch_url(url):
            continue

        # ── get-or-create ExternalLink (serialised) ──────────────────────
        async with db_sem:
            link, _ = await repo.get_or_create_external_link(url)
            link_id = link.id
            needs_fetch = link.fetch_status == FetchStatus.PENDING.value
            if needs_fetch:
                link.fetch_status = FetchStatus.FETCHING.value
                await repo.flush()
            # Link this URL to the post (skip if already linked from body)
            await repo.link_comment_url(comment.post_id, link_id, comment.id)

        if not needs_fetch:
            # URL already fetched — queue for summary only if it has content but no summary
            async with db_sem:
                lnk = await repo.get(ExternalLink, link_id)
                if lnk and lnk.body_excerpt and lnk.ai_summary is None:
                    new_link_ids.append(link_id)
            continue

        # ── HTTP fetch (outside db_sem so other coroutines can run) ──────
        data = await _resolve_and_fetch(url, client, browser, pw_sem)

        # ── write fetch result back (serialised) ─────────────────────────
        async with db_sem:
            lnk = await repo.get(ExternalLink, link_id)
            if lnk is None:
                continue
            lnk.fetch_status = data["fetch_status"]
            lnk.title = data.get("title")
            lnk.description = data.get("description")
            lnk.body_excerpt = data.get("body_excerpt")
            lnk.error_reason = data.get("error_reason")
            lnk.fetched_at = data.get("fetched_at")
            await repo.flush()

            if lnk.fetch_status == FetchStatus.OK.value and lnk.body_excerpt:
                new_link_ids.append(link_id)

    # Mark comment as processed (even if no URLs were usable)
    async with db_sem:
        comment.urls_enriched = True
        await repo.flush()

    return new_link_ids


async def _summarize_comment_links(
    db,
    router: LLMRouter,
    candidates: list[tuple[int, Comment]],
    log_path: Path,
) -> None:
    """Batch LLM-summarize fetched links, using each comment as context.

    Each (link_id, comment) pair gets its own prompt so the summary reflects
    *why* the commenter shared that specific URL.  If multiple comments link to
    the same URL the first comment's context is used.
    """
    from socialgraph.llm.prompts import (
        SUMMARIZE_COMMENT_LINK_SYSTEM,
        SUMMARIZE_COMMENT_LINK_USER,
    )

    # De-duplicate: one entry per link_id (keep first comment for context)
    seen: dict[int, Comment] = {}
    for lid, comment in candidates:
        if lid not in seen:
            seen[lid] = comment

    # Load ExternalLink objects
    link_objects: list[ExternalLink] = []
    comment_for: dict[int, Comment] = {}
    for lid, comment in seen.items():
        lnk = await db.get(ExternalLink, lid)
        if (
            lnk
            and lnk.fetch_status == FetchStatus.OK.value
            and lnk.body_excerpt
            and lnk.ai_summary is None
        ):
            link_objects.append(lnk)
            comment_for[lnk.id] = comment

    if not link_objects:
        logger.info("comment_enrich.summarize_skip", reason="no links need summarization")
        return

    logger.info("comment_enrich.summarize_start", count=len(link_objects))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("a", encoding="utf-8")
    batch_client = router.batch_client
    batch_size = 10

    try:
        for i in range(0, len(link_objects), batch_size):
            batch = link_objects[i : i + batch_size]
            messages_list = []
            for lnk in batch:
                comment = comment_for[lnk.id]
                excerpt = (lnk.body_excerpt or "")[:4000]
                if lnk.description and lnk.description[:100] not in excerpt:
                    excerpt = lnk.description[:500] + "\n\n" + excerpt
                user_msg = SUMMARIZE_COMMENT_LINK_USER.format(
                    commenter_name=comment.author or "Someone",
                    comment_text=(comment.text or "").strip()[:500],
                    title=lnk.title or "",
                    url=lnk.url,
                    excerpt=excerpt,
                )
                messages_list.append(
                    [
                        {"role": "system", "content": SUMMARIZE_COMMENT_LINK_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ]
                )
            try:
                results = await batch_client.batch_chat(
                    messages_list, temperature=0.1, max_tokens=400
                )
                for lnk, messages, summary in zip(batch, messages_list, results, strict=False):
                    if summary and isinstance(summary, str):
                        lnk.ai_summary = summary.strip()[:2000]
                    log_fh.write(
                        json.dumps(
                            {
                                "url": lnk.url,
                                "title": lnk.title,
                                "comment_author": comment_for[lnk.id].author,
                                "comment_text": (comment_for[lnk.id].text or "")[:300],
                                "prompt": messages[-1]["content"],
                                "response": summary,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except Exception as exc:
                logger.error("comment_enrich.summarize_batch_failed", batch_i=i, error=str(exc))
    finally:
        log_fh.close()

    logger.info("comment_enrich.summarize_done", count=len(link_objects), log=str(log_path))

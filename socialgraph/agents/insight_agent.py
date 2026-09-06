"""Groq briefing: post + article + useful comments → structured insight."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.knowledge.comment_rank import useful_comments
from socialgraph.knowledge.insights import PostInsight, parse_insight
from socialgraph.llm.prompts import SYNTHESIZE_INSIGHTS_SYSTEM, SYNTHESIZE_INSIGHTS_USER
from socialgraph.llm.router import LLMRouter
from socialgraph.storage.enums import FetchStatus, PostStatus
from socialgraph.storage.models import Post, PostExternalLink

logger = structlog.get_logger(__name__)

UTC = timezone.utc
INSIGHT_VERSION = 1

_INSIGHT_STATUSES = (
    PostStatus.CLASSIFIED.value,
    PostStatus.GRAPHED.value,
    PostStatus.OK.value,
    PostStatus.ENRICHED.value,
)


class InsightAgent:
    name = "insights"

    def __init__(
        self,
        router: LLMRouter,
        limit: int = 0,
        force: bool = False,
        urns: list[str] | None = None,
        comment_limit: int = 12,
    ) -> None:
        self._router = router
        self._limit = limit
        self._force = force
        self._urns = urns
        self._comment_limit = comment_limit

    async def run(self, ctx: StageContext) -> StageOutput:
        groq = self._router.groq_client
        if groq is None:
            logger.warning("insights.skip", reason="no groq client")
            return StageOutput(stage=self.name, skipped=1, meta={"reason": "no groq client"})

        q = (
            select(Post)
            .where(Post.status.in_(_INSIGHT_STATUSES))
            .options(
                selectinload(Post.comments),
                selectinload(Post.post_links).selectinload(PostExternalLink.external_link),
            )
        )
        if self._urns:
            q = q.where(Post.urn.in_(self._urns))

        result = await ctx.db.scalars(q)
        posts = list(result.all())

        candidates: list[tuple[Post, dict[str, str], str]] = []
        cached = 0
        for post in posts:
            payload = _build_prompt_payload(post, self._comment_limit)
            source_hash = _source_hash(payload)
            existing_is_valid = parse_insight(post.insight_json) is not None
            if not self._force and existing_is_valid and post.insight_source_hash == source_hash:
                cached += 1
                continue
            candidates.append((post, payload, source_hash))

        if self._limit:
            candidates = candidates[: self._limit]

        if not candidates:
            return StageOutput(
                stage=self.name,
                skipped=max(cached, 1),
                meta={"reason": "no posts need insights", "cached": cached},
            )

        processed = failed = 0
        checkpoint_size = max(1, ctx.settings.batch_size)
        for index, (post, payload, source_hash) in enumerate(candidates, start=1):
            try:
                raw = await asyncio.to_thread(
                    groq.complete,
                    [
                        {"role": "system", "content": SYNTHESIZE_INSIGHTS_SYSTEM},
                        {
                            "role": "user",
                            "content": SYNTHESIZE_INSIGHTS_USER.format(**payload),
                        },
                    ],
                    {"type": "json_object"},
                    0.1,
                )
                insight = parse_insight(raw)
                if insight is None:
                    failed += 1
                    logger.warning("insights.empty", urn=post.urn)
                    continue
                insight = _ground_insight(insight, post)
                post.insight_json = insight.to_json()
                post.insight_source_hash = source_hash
                post.insight_generated_at = datetime.now(UTC)
                processed += 1
            except Exception as exc:
                logger.error("insights.post_failed", urn=post.urn, error=str(exc))
                failed += 1

            if index % checkpoint_size == 0:
                await ctx.db.commit()
                logger.info(
                    "insights.progress",
                    completed=index,
                    total=len(candidates),
                    processed=processed,
                    failed=failed,
                )

        await ctx.db.commit()
        logger.info("insights.complete", processed=processed, failed=failed)
        return StageOutput(
            stage=self.name,
            processed=processed,
            skipped=cached,
            failed=failed,
            meta={"cached": cached, "version": INSIGHT_VERSION},
        )


def _build_prompt_payload(post: Post, comment_limit: int) -> dict[str, str]:
    articles: list[str] = []
    comment_links: list[str] = []
    for pel in post.post_links or []:
        link = pel.external_link
        if link is None or link.fetch_status != FetchStatus.OK.value:
            continue
        summary = link.ai_summary or link.description or ""
        excerpt = (link.body_excerpt or "")[:1800]
        block = f"- {link.title or link.url}\n  URL: {link.url}\n  {summary}\n  {excerpt}"
        if pel.context == "comment":
            comment_links.append(block)
        else:
            articles.append(block)

    comment_blocks: list[str] = []
    for comment in useful_comments(post.comments, limit=comment_limit):
        author = comment.author or "Someone"
        kind = comment.kind or "insight"
        comment_blocks.append(f"- [{kind}] {author}: {(comment.text or '').strip()[:600]}")

    return {
        "author": post.author or "Unknown",
        "title": (post.title or "").replace("\n", " — ") or "(untitled)",
        "post": (post.content or "")[:2500],
        "articles": "\n".join(articles) if articles else "(none)",
        "comments": "\n".join(comment_blocks) if comment_blocks else "(none)",
        "comment_links": "\n".join(comment_links) if comment_links else "(none)",
    }


def _source_hash(payload: dict[str, str]) -> str:
    """Hash every source used by the briefing so stale insights self-invalidate."""
    canonical = json.dumps(
        {"version": INSIGHT_VERSION, "payload": payload},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ground_insight(insight: PostInsight, post: Post) -> PostInsight:
    """Drop resource URLs and commenter attributions absent from the supplied sources."""
    allowed_urls = {
        pel.external_link.url.rstrip("/")
        for pel in post.post_links or []
        if pel.external_link is not None and pel.external_link.url
    }
    resources = [
        resource
        for resource in insight.resources
        if resource.url and resource.url.rstrip("/") in allowed_urls
    ]

    actual_authors = {
        " ".join((comment.author or "Someone").casefold().split()): comment.author or "Someone"
        for comment in useful_comments(post.comments, limit=100)
    }
    community = []
    for item in insight.community_insights:
        candidate = " ".join(item.author.casefold().split())
        canonical = actual_authors.get(candidate)
        if canonical is None and len(candidate) >= 3:
            canonical = next(
                (
                    actual
                    for normalized, actual in actual_authors.items()
                    if candidate in normalized or normalized in candidate
                ),
                None,
            )
        if canonical and item.claim.strip():
            community.append(replace(item, author=canonical))

    return replace(insight, community_insights=community, resources=resources)

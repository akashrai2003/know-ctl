"""Enrich agent: fetch external URLs, extract content, process comments."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime

import httpx
import structlog
import trafilatura
from bs4 import BeautifulSoup
from sqlalchemy import select

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.storage.models import ExternalLink, Post
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)

FETCH_TIMEOUT = 10.0
MAX_RESPONSE_BYTES = 2_000_000
CONCURRENCY = 10

BLOCKED_URL_PATTERNS = [
    "linkedin.com",
    "twitter.com",
    "x.com",
    "t.co",
    "facebook.com",
    "instagram.com",
    "lnkd.in",
]

URL_RE = re.compile(r"https?://[^\s\"'>]+")


def should_fetch_url(url: str) -> bool:
    u = url.lower().strip()
    if not u.startswith("http"):
        return False
    if u.startswith("#") or u.startswith("mailto:") or u.startswith("tel:"):
        return False
    return not any(p in u for p in BLOCKED_URL_PATTERNS)


def _extract_urls(text: str) -> list[str]:
    return URL_RE.findall(text)


class EnrichAgent:
    name = "enrich"

    async def run(self, ctx: StageContext) -> StageOutput:
        result = await ctx.db.scalars(
            select(Post).where(Post.status == "ingested")
        )
        posts = list(result.all())

        if not posts:
            return StageOutput(stage=self.name, skipped=1, meta={"reason": "no ingested posts"})

        repo = Repo(ctx.db)
        semaphore = asyncio.Semaphore(CONCURRENCY)
        processed = failed = 0

        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SocialGraphBot/1.0)"},
            follow_redirects=True,
        ) as client:
            async def enrich_one(post: Post) -> None:
                nonlocal processed, failed
                async with semaphore:
                    try:
                        await _enrich_post(post, repo, client, ctx.settings.max_comments)
                        post.status = "enriched"
                        processed += 1
                    except Exception as exc:
                        logger.error("enrich.post_failed", urn=post.urn, error=str(exc))
                        post.status = "failed"
                        failed += 1

            await asyncio.gather(*[enrich_one(p) for p in posts])

        await ctx.db.commit()
        logger.info("enrich.complete", processed=processed, failed=failed)
        return StageOutput(stage=self.name, processed=processed, failed=failed)


async def _enrich_post(post: Post, repo: Repo, client: httpx.AsyncClient, max_comments: int) -> None:
    urls = _extract_urls(post.content)
    for url in urls:
        if not should_fetch_url(url):
            continue
        link, created = await repo.get_or_create_external_link(url)
        await repo.link_post_to_url(post.id, link.id, context="body")
        if created:
            await _fetch_link(link, client)


async def _fetch_link(link: ExternalLink, client: httpx.AsyncClient) -> None:
    link.fetch_status = "fetching"
    try:
        chunks: list[bytes] = []
        total = 0
        async with client.stream("GET", link.url) as resp:
            if resp.status_code != 200:
                link.fetch_status = "failed"
                link.error_reason = f"http_{resp.status_code}"
                return
            ct = resp.headers.get("content-type", "")
            if not any(x in ct for x in ["text/html", "text/plain", "application/xhtml"]):
                link.fetch_status = "skipped"
                return
            async for chunk in resp.aiter_bytes(8192):
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    break
        html = b"".join(chunks)
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("title")
        og_desc = soup.find("meta", property="og:description")
        link.title = title_tag.text.strip()[:512] if title_tag else None
        link.description = (og_desc.get("content", "")[:1024] if og_desc else None)
        link.body_excerpt = text[:2000] if text else None
        link.fetch_status = "ok"
        link.fetched_at = datetime.utcnow()
    except Exception as exc:
        link.fetch_status = "failed"
        link.error_reason = str(exc)[:256]

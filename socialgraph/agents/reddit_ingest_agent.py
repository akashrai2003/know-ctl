"""Reddit ingest agent: load saved posts from Reddit via OAuth API into the database."""

from __future__ import annotations

import structlog

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.connectors.reddit import RedditAPIConnector
from socialgraph.storage.enums import PostStatus
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)


class RedditIngestAgent:
    """Ingest saved posts from Reddit via asyncpraw OAuth API."""

    name = "ingest"

    def __init__(self) -> None:
        pass

    async def run(self, ctx: StageContext) -> StageOutput:
        repo = Repo(ctx.db)
        posts = await repo.get_all_posts(platform="reddit")
        already_known_urns = {p.urn for p in posts}

        connector = RedditAPIConnector(ctx.settings)
        raw_posts = await connector.fetch_saved_posts(already_known_urns)

        processed = skipped = 0
        for rp in raw_posts:
            post, created = await repo.get_or_create_post(rp.urn, rp.platform)
            if not created:
                skipped += 1
                continue
            post.author = rp.author
            post.subtitle = rp.subtitle
            post.date_raw = rp.date_raw
            post.content = rp.content
            post.source_url = rp.source_url
            post.status = PostStatus.INGESTED.value
            processed += 1

        await ctx.db.commit()
        logger.info("reddit_ingest.complete", processed=processed, skipped=skipped)
        return StageOutput(stage=self.name, processed=processed, skipped=skipped)

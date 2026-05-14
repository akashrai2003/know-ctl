"""Ingest agent: load raw posts from JSON (or Playwright) into the database."""
from __future__ import annotations

from pathlib import Path

import structlog

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.connectors.base import RawPost
from socialgraph.connectors.linkedin import LinkedInJSONConnector
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)


class IngestAgent:
    name = "ingest"

    def __init__(self, json_path: Path) -> None:
        self._json_path = json_path

    async def run(self, ctx: StageContext) -> StageOutput:
        connector = LinkedInJSONConnector(self._json_path)
        raw_posts: list[RawPost] = await connector.fetch_saved_posts()

        repo = Repo(ctx.db)
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
            post.status = "ingested"
            processed += 1

        await ctx.db.commit()
        logger.info("ingest.complete", processed=processed, skipped=skipped)
        return StageOutput(stage=self.name, processed=processed, skipped=skipped)

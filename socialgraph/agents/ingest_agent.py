"""Ingest agent: load raw posts from JSON (or Playwright) into the database."""

from __future__ import annotations

from pathlib import Path

import structlog

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.connectors.base import RawPost
from socialgraph.connectors.linkedin import LinkedInJSONConnector
from socialgraph.storage.enums import PostStatus
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)


class IngestAgent:
    name = "ingest"

    def __init__(self, json_path: Path | None = None, live_mode: bool = False) -> None:
        self._json_path = json_path
        self._live_mode = live_mode

    async def run(self, ctx: StageContext) -> StageOutput:
        repo = Repo(ctx.db)
        raw_posts: list[RawPost]
        if self._live_mode:
            from socialgraph.connectors.linkedin import LinkedInPlaywrightConnector

            posts = await repo.get_all_posts()
            already_known_urns = {p.urn for p in posts}
            live_connector = LinkedInPlaywrightConnector(ctx.settings)
            raw_posts = await live_connector.fetch_saved_posts(already_known_urns)
        else:
            if not self._json_path:
                raise ValueError("json_path must be provided if live_mode is False")
            json_connector = LinkedInJSONConnector(self._json_path)
            raw_posts = await json_connector.fetch_saved_posts()

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
        logger.info("ingest.complete", processed=processed, skipped=skipped)
        return StageOutput(stage=self.name, processed=processed, skipped=skipped)

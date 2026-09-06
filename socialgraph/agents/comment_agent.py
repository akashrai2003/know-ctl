"""Comment agent: scrape LinkedIn comments for saved posts via Voyager API."""

from __future__ import annotations

import structlog

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.browser.playwright_client import PlaywrightClient
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)

BATCH_SIZE = 20  # URNs per Playwright page session


class CommentAgent:
    name = "comments"

    def __init__(
        self,
        limit: int = 0,
        force: bool = False,
        max_per_post: int = 80,
        urns: list[str] | None = None,
    ) -> None:
        self._limit = limit
        self._force = force
        self._max_per_post = max_per_post
        self._urns = urns

    async def run(self, ctx: StageContext) -> StageOutput:
        repo = Repo(ctx.db)

        if self._max_per_post == 0:
            return StageOutput(
                stage=self.name,
                skipped=1,
                meta={"reason": "comment fetching disabled (max_per_post=0)"},
            )

        if self._urns:
            posts = await repo.get_posts_by_urns(self._urns)
            if not self._force:
                posts = [p for p in posts if not p.comments_fetched]
        else:
            posts = await repo.get_posts_for_comments(
                limit=self._limit, include_fetched=self._force
            )

        if self._force and posts:
            # Mark refresh targets retryable before network I/O, but retain the
            # current rows until a successful replacement is available.
            for post in posts:
                post.comments_fetched = False
            await ctx.db.commit()

        if not posts:
            return StageOutput(
                stage=self.name, skipped=1, meta={"reason": "all posts already have comments"}
            )

        logger.info("comments.start", total=len(posts))
        processed = failed = total_comments = 0

        # Batch into groups of BATCH_SIZE
        for batch_start in range(0, len(posts), BATCH_SIZE):
            batch = posts[batch_start : batch_start + BATCH_SIZE]
            urn_to_post = {p.urn: p for p in batch}
            urns = list(urn_to_post.keys())

            try:
                async with PlaywrightClient(ctx.settings) as client:
                    comment_map: dict[str, list[dict]] = await client.fetch_comments_batch(
                        urns, max_per_post=self._max_per_post
                    )
            except Exception as exc:
                logger.error("comments.batch_failed", batch_start=batch_start, error=str(exc))
                failed += len(batch)
                continue

            missing_urns = set(urns) - set(comment_map)
            failed += len(missing_urns)
            for urn in missing_urns:
                logger.warning("comments.post_retryable_failure", urn=urn)

            for urn, comments in comment_map.items():
                matched_post = urn_to_post.get(urn)
                if not matched_post:
                    continue
                try:
                    async with ctx.db.begin_nested():
                        if self._force:
                            await repo.delete_comments_for_post(matched_post.id)
                        added = await repo.bulk_insert_comments(matched_post.id, comments)
                        matched_post.comments_fetched = True
                        # Any thread refresh changes the evidence used by the briefing.
                        matched_post.insight_json = None
                        matched_post.insight_source_hash = None
                        matched_post.insight_generated_at = None
                    total_comments += added
                    processed += 1
                except Exception as exc:
                    logger.error("comments.insert_failed", urn=urn, error=str(exc))
                    failed += 1

            await ctx.db.commit()
            logger.info(
                "comments.batch_done",
                batch_end=batch_start + len(batch),
                total=len(posts),
                comments_so_far=total_comments,
            )

        logger.info(
            "comments.complete", processed=processed, failed=failed, comments=total_comments
        )
        return StageOutput(
            stage=self.name,
            processed=processed,
            failed=failed,
            meta={
                "total_comments": total_comments,
                "retryable_failures": failed,
                "scan_limit_per_post": self._max_per_post,
            },
        )

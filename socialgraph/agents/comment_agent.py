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

    def __init__(self, limit: int = 0, force: bool = False, max_per_post: int = 50) -> None:
        self._limit = limit
        self._force = force
        self._max_per_post = max_per_post

    async def run(self, ctx: StageContext) -> StageOutput:
        repo = Repo(ctx.db)

        if self._force:
            # Reset all posts so they re-fetch comments, and delete stale comment
            # rows so bulk_insert_comments doesn't skip them by rank match.
            from sqlalchemy import select as sql_select
            from sqlalchemy import update

            from socialgraph.storage.models import Post
            await ctx.db.execute(update(Post).values(comments_fetched=False))
            await ctx.db.flush()

            # Delete all existing comments so fresh data (incl. replies) replaces them
            all_post_ids = list(await ctx.db.scalars(sql_select(Post.id)))
            deleted_total = 0
            for pid in all_post_ids:
                deleted_total += await repo.delete_comments_for_post(pid)
            await ctx.db.commit()
            logger.info("comments.force_cleared", deleted=deleted_total)

        posts = await repo.get_posts_needing_comments(limit=self._limit)

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
                for p in batch:
                    p.comments_fetched = True  # mark done to avoid infinite retries
                failed += len(batch)
                await ctx.db.commit()
                continue

            for urn, comments in comment_map.items():
                post = urn_to_post.get(urn)
                if not post:
                    continue
                try:
                    added = await repo.bulk_insert_comments(post.id, comments)
                    total_comments += added
                    post.comments_fetched = True
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

        logger.info("comments.complete", processed=processed, failed=failed, comments=total_comments)
        return StageOutput(
            stage=self.name,
            processed=processed,
            failed=failed,
            meta={"total_comments": total_comments},
        )

"""Reddit comment agent: fetch comments via asyncpraw API.

Unlike the LinkedIn CommentAgent (which uses Playwright browser automation),
this agent talks directly to the Reddit API through the RedditAPIConnector.
Comment threads are fetched per-submission and stored in the same Comment
model used by LinkedIn posts, enabling the downstream rank/enrich/insight
pipeline to operate identically on both platforms.
"""

from __future__ import annotations

import structlog

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.connectors.reddit import RedditAPIConnector
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)


class RedditCommentAgent:
    """Fetch Reddit comment threads for saved submissions via API."""

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
            posts = [p for p in posts if p.platform == "reddit"]
            if not self._force:
                posts = [p for p in posts if not p.comments_fetched]
        else:
            posts = await repo.get_posts_for_comments(
                limit=self._limit,
                include_fetched=self._force,
                platform="reddit",
            )

        if not posts:
            return StageOutput(
                stage=self.name,
                skipped=1,
                meta={"reason": "no reddit posts need comments"},
            )

        logger.info("reddit_comments.start", total=len(posts))
        connector = RedditAPIConnector(ctx.settings)
        processed = failed = total_comments = 0

        for post in posts:
            # Extract submission ID from URN: "urn:reddit:submission:<id>"
            submission_id = post.urn.split(":")[-1]
            try:
                comments = await connector.fetch_comments_for_submission(
                    submission_id,
                    max_comments=self._max_per_post,
                )

                if self._force:
                    await repo.delete_comments_for_post(post.id)

                added = await repo.bulk_insert_comments(post.id, comments)
                post.comments_fetched = True
                # Invalidate stale briefing so insights agent regenerates it
                post.insight_json = None
                post.insight_source_hash = None
                post.insight_generated_at = None
                total_comments += added
                processed += 1
            except Exception as exc:
                logger.error("reddit_comments.failed", urn=post.urn, error=str(exc))
                failed += 1

        await ctx.db.commit()
        logger.info(
            "reddit_comments.complete",
            processed=processed,
            failed=failed,
            comments=total_comments,
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

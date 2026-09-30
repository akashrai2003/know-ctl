"""Reddit connector: fetch saved posts and comments via Reddit API (asyncpraw).

Uses OAuth2 'script' type authentication for personal account access.
Saved comments are resolved to their parent submission to keep the data
model consistent — one Post row per unique submission.
"""

from __future__ import annotations

from datetime import datetime, timezone

import asyncpraw
import asyncpraw.models
import structlog

from socialgraph.connectors.base import RawPost

logger = structlog.get_logger(__name__)

UTC = timezone.utc


class RedditAPIConnector:
    """Fetch saved posts and comments from Reddit via OAuth API."""

    platform = "reddit"

    def __init__(self, settings) -> None:  # type: ignore[type-arg]
        self._settings = settings

    def is_configured(self) -> bool:
        """Check if all required Reddit API credentials are provided."""
        return bool(
            self._settings.reddit_client_id
            and self._settings.reddit_client_secret
            and self._settings.reddit_username
            and self._settings.reddit_password
        )

    def _build_reddit(self) -> asyncpraw.Reddit:
        """Build an asyncpraw Reddit instance from settings."""
        if not self.is_configured():
            raise ValueError(
                "Reddit credentials are incomplete. Please set SG_REDDIT_CLIENT_ID, "
                "SG_REDDIT_CLIENT_SECRET, SG_REDDIT_USERNAME, and SG_REDDIT_PASSWORD."
            )
        return asyncpraw.Reddit(
            client_id=self._settings.reddit_client_id,
            client_secret=self._settings.reddit_client_secret,
            username=self._settings.reddit_username,
            password=self._settings.reddit_password,
            user_agent=(f"python:social-graph:v0.2 (by /u/{self._settings.reddit_username})"),
        )

    async def fetch_saved_posts(self, already_known_urns: set[str] | None = None) -> list[RawPost]:
        """Fetch user's saved submissions and saved comments from Reddit.

        Saved comments are resolved to their parent submission to keep
        the data model consistent (one Post row per submission).

        Returns up to 1,000 items (Reddit API hard limit on saved listings).
        """
        reddit = self._build_reddit()
        posts: list[RawPost] = []
        seen_urns: set[str] = set(already_known_urns or set())

        try:
            user = await reddit.user.me()
            async for item in user.saved(limit=None):
                if isinstance(item, asyncpraw.models.Submission):
                    urn = f"urn:reddit:submission:{item.id}"
                    if urn in seen_urns:
                        continue
                    seen_urns.add(urn)

                    # Build content from selftext (for self-posts) or URL
                    content = item.selftext or ""
                    if not item.is_self and item.url:
                        content = f"[Link post] {item.url}\n\n{content}".strip()

                    created = datetime.fromtimestamp(item.created_utc, tz=UTC)

                    posts.append(
                        RawPost(
                            platform="reddit",
                            urn=urn,
                            author=str(item.author) if item.author else None,
                            subtitle=f"r/{item.subreddit}",
                            date_raw=created.strftime("%Y-%m-%d %H:%M"),
                            content=f"{item.title}\n\n{content}".strip(),
                            source_url=f"https://www.reddit.com{item.permalink}",
                        )
                    )

                elif isinstance(item, asyncpraw.models.Comment):
                    # Resolve saved comment → parent submission
                    submission = item.submission
                    await submission.load()
                    urn = f"urn:reddit:submission:{submission.id}"
                    if urn in seen_urns:
                        continue
                    seen_urns.add(urn)

                    content = submission.selftext or ""
                    if not submission.is_self and submission.url:
                        content = f"[Link post] {submission.url}\n\n{content}".strip()

                    created = datetime.fromtimestamp(submission.created_utc, tz=UTC)

                    posts.append(
                        RawPost(
                            platform="reddit",
                            urn=urn,
                            author=(str(submission.author) if submission.author else None),
                            subtitle=f"r/{submission.subreddit}",
                            date_raw=created.strftime("%Y-%m-%d %H:%M"),
                            content=f"{submission.title}\n\n{content}".strip(),
                            source_url=f"https://www.reddit.com{submission.permalink}",
                        )
                    )

        finally:
            await reddit.close()

        logger.info("reddit.api_loaded", count=len(posts))
        return posts

    async def fetch_comments_for_submission(
        self,
        submission_id: str,
        max_comments: int = 80,
        replace_more_limit: int = 10,
    ) -> list[dict]:
        """Fetch the comment tree for a single Reddit submission.

        Uses ``replace_more()`` to expand collapsed comment branches, then
        flattens the tree into a list of comment dicts compatible with the
        existing ``Comment`` model schema.

        Args:
            submission_id: Reddit submission ID (e.g. ``"abc123"``).
            max_comments: Maximum comments to return.
            replace_more_limit: How many ``MoreComments`` placeholders to expand
                (each costs one API call).

        Returns:
            Flat list of comment dicts with keys: author, text, is_reply,
            rank, comment_urn, parent_comment_urn, score, is_op.
        """
        reddit = self._build_reddit()
        comments_out: list[dict] = []

        try:
            submission = await reddit.submission(id=submission_id)
            await submission.load()
            await submission.comments.replace_more(limit=replace_more_limit)

            all_comments = submission.comments.list()
            for rank, comment in enumerate(all_comments[:max_comments]):
                if not hasattr(comment, "body"):
                    continue  # skip MoreComments remnants
                is_reply = comment.parent_id.startswith("t1_")
                comments_out.append(
                    {
                        "author": (str(comment.author) if comment.author else "[deleted]"),
                        "text": comment.body or "",
                        "is_reply": is_reply,
                        "rank": rank,
                        "comment_urn": f"t1_{comment.id}",
                        "parent_comment_urn": (comment.parent_id if is_reply else None),
                    }
                )
        finally:
            await reddit.close()

        return comments_out

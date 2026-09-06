from __future__ import annotations

import asyncio

import structlog
from playwright.async_api import Page

from socialgraph.config.settings import Settings

logger = structlog.get_logger(__name__)


class SavedPostsPage:
    def __init__(self, page: Page, settings: Settings, extract_js: str) -> None:
        self.page = page
        self.settings = settings
        self.extract_js = extract_js

    async def fetch_saved_posts(self, known_urns: list[str] | None = None) -> list[dict]:
        """Navigate to saved posts, intercept Voyager responses, and run JS extraction."""
        voyager_fired = asyncio.Event()

        def _report_progress(progress: object) -> None:
            if not isinstance(progress, dict):
                return
            logger.info(
                "linkedin.saved_posts_progress",
                phase=progress.get("phase"),
                pages=progress.get("pages"),
                extracted=progress.get("extracted"),
                hydrated=progress.get("hydrated"),
                hydration_total=progress.get("hydrationTotal"),
            )

        # The extractor paginates inside the browser context. Bridge progress
        # back to Python so a full-library scrape does not look frozen.
        await self.page.expose_function("sgReportSavedPostsProgress", _report_progress)

        def _on_response(response) -> None:
            if "SEARCH_MY_ITEMS_SAVED_POSTS" in response.url or (
                "my-items" in response.url and "savedPosts" in response.url
            ):
                voyager_fired.set()

        self.page.on("response", _on_response)

        await self.page.goto(
            "https://www.linkedin.com/my-items/saved-posts/",
            wait_until="domcontentloaded",
            timeout=30_000,
        )

        # Wait up to 15 s for Voyager API; fall through gracefully if it doesn't fire
        try:
            await asyncio.wait_for(voyager_fired.wait(), timeout=15)
            logger.info("linkedin.voyager_detected")
        except asyncio.TimeoutError:
            logger.warning(
                "linkedin.voyager_timeout", msg="Voyager API not detected, proceeding anyway"
            )

        # Small pause so the URL is fully registered in performance entries
        await asyncio.sleep(2)

        logger.info(
            "linkedin.saved_posts_scan_started",
            mode="incremental" if known_urns else "full",
            request_timeout_seconds=30,
        )
        result = await self.page.evaluate(self.extract_js, known_urns or [])
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(f"LinkedIn JS extraction failed: {result['error']}")

        if isinstance(result, dict) and "posts" in result:
            posts = result["posts"]
            pagination_error = result.get("paginationError")
            if pagination_error:
                logger.warning(
                    "linkedin.saved_posts_pagination_stopped",
                    error=pagination_error,
                    partial_count=len(posts),
                )
            errors = result.get("hydrationErrors", [])
            if errors:
                logger.warning(
                    "linkedin.hydration_errors",
                    count=len(errors),
                    samples=[e["urn"] + ": " + e["error"] for e in errors[:5]],
                )
            logger.info("linkedin.playwright_extracted", count=len(posts))
            return posts

        logger.info("linkedin.playwright_extracted", count=len(result))
        return result

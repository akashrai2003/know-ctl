"""Playwright-based browser automation for LinkedIn saved posts refresh."""

from __future__ import annotations

import asyncio
import contextlib
import pathlib
from typing import Any

import structlog
from playwright.async_api import Browser, BrowserContext, Playwright

from socialgraph.browser.comments_page import CommentsPage
from socialgraph.browser.login_page import LinkedInLoginPage
from socialgraph.browser.saved_posts_page import SavedPostsPage
from socialgraph.browser.session_manager import BrowserSessionManager
from socialgraph.config.settings import Settings

logger = structlog.get_logger(__name__)

_HERE = pathlib.Path(__file__).parent

# Load externalized JS scripts dynamically
EXTRACT_SAVED_POSTS_JS = (_HERE / "js" / "extract_saved_posts.js").read_text(encoding="utf-8")
FETCH_COMMENTS_JS = (_HERE / "js" / "fetch_comments.js").read_text(encoding="utf-8")
EXTRACT_COMMENTS_JS = (_HERE / "js" / "extract_comments.js").read_text(encoding="utf-8")


class PlaywrightClient:
    """Context manager wrapping a Playwright browser for LinkedIn automation."""

    _STATE_PATH = ".socialgraph/linkedin_state.json"
    _pw: Playwright | None
    _browser: Browser | None
    _context: BrowserContext | None

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session_manager = BrowserSessionManager(settings)
        self._pw = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> PlaywrightClient:
        await self._session_manager.start()
        # Expose references for compatibility
        self._pw = self._session_manager.pw
        self._browser = self._session_manager.browser
        self._context = self._session_manager.context
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._session_manager.stop()

    async def new_page(self):
        return await self._session_manager.new_page()

    async def _is_logged_in(self) -> bool:
        return await self._session_manager.is_logged_in()

    async def login_linkedin(self):
        """Log in to LinkedIn (skipped if session cookie is still valid)."""
        page = await self.new_page()
        login_page = LinkedInLoginPage(page, self._settings)
        # Pass self._is_logged_in to maintain signature compatibility
        return await login_page.login(self._is_logged_in)

    async def fetch_saved_posts(self, known_urns: list[str] | None = None) -> list[dict]:
        """Log in, navigate to saved posts, and extract via injected JS.

        If the saved session state is stale and results in an extraction failure,
        this will automatically clear the state file and retry with a fresh login.
        """
        try:
            page = await self.login_linkedin()
            saved_posts_page = SavedPostsPage(page, self._settings, EXTRACT_SAVED_POSTS_JS)
            return await saved_posts_page.fetch_saved_posts(known_urns)
        except Exception as e:
            state_file = pathlib.Path(self._STATE_PATH)
            if state_file.exists():
                logger.warning("linkedin.session_stale_clearing_state", error=str(e))
                with contextlib.suppress(Exception):
                    state_file.unlink()

                # Stop and restart session manager to clear cookies/context
                await self._session_manager.stop()
                await self._session_manager.start()
                self._pw = self._session_manager.pw
                self._browser = self._session_manager.browser
                self._context = self._session_manager.context

                logger.info("linkedin.retrying_with_fresh_login")
                page = await self.login_linkedin()
                saved_posts_page = SavedPostsPage(page, self._settings, EXTRACT_SAVED_POSTS_JS)
                return await saved_posts_page.fetch_saved_posts(known_urns)
            else:
                raise

    async def fetch_comments_batch(
        self, urns: list[str], max_per_post: int = 50
    ) -> dict[str, list[dict]]:
        """Fetch top-level comments and nested replies for each URN by visiting
        each post page and expanding reply threads via DOM interaction.

        Returns a dict mapping URN → list of {author, text, rank, has_external_url,
        is_reply, comment_urn, parent_comment_urn}.
        """
        results: dict[str, list[dict]] = {}
        page = await self.login_linkedin()
        comments_page = CommentsPage(page, self._settings, EXTRACT_COMMENTS_JS)

        for urn in urns:
            try:
                results[urn] = await comments_page.fetch_comments_for_urn(urn, max_per_post)
            except Exception as exc:
                # Omit failed URNs so CommentAgent leaves them retryable instead
                # of permanently recording a successful empty thread.
                logger.warning("comments.urn_failed", urn=urn, error=str(exc))
            await asyncio.sleep(0.5)

        await page.close()
        return results

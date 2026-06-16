from __future__ import annotations

import asyncio
import contextlib

import structlog
from playwright.async_api import Page

from socialgraph.config.settings import Settings

logger = structlog.get_logger(__name__)


class CommentsPage:
    def __init__(self, page: Page, settings: Settings, extract_comments_js: str) -> None:
        self.page = page
        self.settings = settings
        self.extract_comments_js = extract_comments_js

    async def fetch_comments_for_urn(self, urn: str, max_per_post: int = 50) -> list[dict]:
        """Fetch comments (top-level + nested replies) for a single post URN
        by visiting the post page, clicking 'Load more comments', and expanding
        all 'See previous replies' threads.
        """
        post_url = f"https://www.linkedin.com/feed/update/{urn}/"
        collected: list[dict] = []

        try:
            await self.page.goto(post_url, wait_until="domcontentloaded", timeout=30_000)

            # Dismiss any "Sign in to view more" modal that LinkedIn shows
            with contextlib.suppress(Exception):
                dismiss = self.page.locator(
                    'button[aria-label="Dismiss"], button.modal__dismiss, '
                    'button[data-tracking-control-name="public_jobs_nav-header-signin"]'
                ).first
                if await dismiss.is_visible(timeout=2_000):
                    await dismiss.click()
                    await asyncio.sleep(0.5)

            # Wait for first comments to render
            with contextlib.suppress(Exception):
                await self.page.wait_for_selector("article.comments-comment-entity", timeout=8_000)
            await asyncio.sleep(1)

            # ── Step 1: load all top-level comments ──────────────────────────
            load_more_sel = (
                "button.comments-comments-list__load-more-comments-button, "
                "[class*='load-more-comments'], "
                "button[aria-label*='Load more comments'], "
                "button[aria-label*='Show more comments']"
            )
            while True:
                try:
                    btn = self.page.locator(load_more_sel).first
                    if not await btn.is_visible(timeout=2_000):
                        break
                    await btn.click(timeout=5_000)
                    await asyncio.sleep(1.5)
                except Exception:
                    break

            # ── Step 2: expand all reply threads ─────────────────────────────
            # LinkedIn shows "See previous replies" for threads with older replies.
            # Click all such buttons repeatedly until none remain visible.
            reply_expand_sel = (
                "button[aria-label*='Load previous replies'], "
                "button[aria-label*='View replies'], "
                "button[aria-label*='load previous replies'], "
                "button[aria-label*='view replies']"
            )
            max_reply_rounds = 10
            for _ in range(max_reply_rounds):
                btns = await self.page.locator(reply_expand_sel).all()
                if not btns:
                    break
                any_clicked = False
                for btn in btns:
                    try:
                        if await btn.is_visible(timeout=500):
                            await btn.scroll_into_view_if_needed()
                            await btn.click(timeout=5_000)
                            await asyncio.sleep(0.8)
                            any_clicked = True
                    except Exception:
                        pass
                if not any_clicked:
                    break
                await asyncio.sleep(0.5)

            # ── Step 3: extract all visible comments + replies from DOM ───────
            batch = await self.page.evaluate(self.extract_comments_js)
            for i, c in enumerate(batch):
                c["rank"] = i
            collected = batch

            logger.info(
                "comments.post_done",
                urn=urn,
                count=len(collected),
                replies=sum(1 for c in collected if c.get("is_reply")),
            )

        except Exception as exc:
            logger.error("comments.page_failed", urn=urn, error=str(exc))

        return collected[:max_per_post]

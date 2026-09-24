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

    async def fetch_comments_for_urn(self, urn: str, max_per_post: int = 80) -> list[dict]:
        """Fetch comments (top-level + nested replies) for a single post URN
        by visiting the post page, scrolling to lazily load comments, clicking
        'Load more comments', and expanding all reply threads.
        """
        post_url = f"https://www.linkedin.com/feed/update/{urn}/"
        collected: list[dict] = []

        if max_per_post <= 0:
            return collected

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

            # Initial scroll to comments section anchor
            await self.page.evaluate("""() => {
                const anchor = document.querySelector(
                    '[componentkey*="commentsSectionAnchorRef"], [data-component-type="LazyColumn"], [data-placeholder*="comment"]'
                );
                if (anchor) anchor.scrollIntoView({behavior: "smooth", block: "center"});
                else {
                    const main = document.querySelector('main') || document.documentElement;
                    main.scrollTop = Math.min(1500, main.scrollHeight);
                }
            }""")
            await asyncio.sleep(1.5)

            # ── Step 1: load top-level comments by scrolling & clicking more ──────
            load_more_sel = (
                "button.comments-comments-list__load-more-comments-button, "
                "[class*='load-more-comments'], "
                "button[aria-label*='Load more comments'], "
                "button[aria-label*='Show more comments'], "
                "button[aria-label*='previous comments']"
            )

            prev_count = -1
            stalls = 0
            max_scroll_rounds = 20

            for _ in range(max_scroll_rounds):
                # Check visible comments (supports both modern SDUI and legacy)
                visible_count = await self.page.evaluate("""() => {
                    const sdui = document.querySelectorAll(
                        '[componentkey^="CommentComponentReference_"], [componentkey*="urn:li:comment"]'
                    );
                    if (sdui.length > 0) return sdui.length;
                    return document.querySelectorAll('article.comments-comment-entity, .comments-comment-item').length;
                }""")

                if visible_count >= max_per_post:
                    break

                # Try clicking explicit load-more button if present
                with contextlib.suppress(Exception):
                    btn = self.page.locator(load_more_sel).first
                    if await btn.is_visible(timeout=500):
                        await btn.click(timeout=2_000)
                        await asyncio.sleep(1.0)

                # Scroll the scrollable container (LinkedIn uses <main> with overflow-y: auto)
                await self.page.evaluate("""() => {
                    const main = document.querySelector('main') || document.documentElement;
                    main.scrollTop = main.scrollHeight;
                }""")
                await asyncio.sleep(1.2)

                if visible_count == prev_count:
                    stalls += 1
                    if stalls >= 3:
                        break
                else:
                    stalls = 0
                prev_count = visible_count

            # ── Step 2: expand all reply threads ─────────────────────────────
            # In LinkedIn's modern SDUI, reply expansion elements are clickable <div> or <p>
            # elements with componentkey containing "LoadMoreReplies" or text like "See previous replies".
            # In legacy UI, they are <button> elements with aria-label.
            max_reply_rounds = 5
            for _ in range(max_reply_rounds):
                clicked_count = await self.page.evaluate("""() => {
                    let clicked = 0;
                    // SDUI: elements with componentkey containing LoadMoreReplies
                    const sdui = Array.from(document.querySelectorAll('[componentkey*="LoadMoreReplies" i]'));
                    for (const el of sdui) {
                        try {
                            el.click();
                            clicked++;
                        } catch(e) {}
                    }
                    // SDUI / general: elements whose text includes 'previous replies'
                    const allEls = Array.from(document.querySelectorAll('div, button, p, span'));
                    for (const el of allEls) {
                        const txt = (el.innerText || '').trim().toLowerCase();
                        if ((txt.includes('previous replies') || txt.includes('previous reply') || 
                             txt.includes('load replies') || txt.includes('view replies') || 
                             txt.includes('see replies') || txt.includes('show replies')) && 
                            el.children.length <= 1) {
                            try {
                                el.click();
                                clicked++;
                            } catch(e) {}
                        }
                    }
                    return clicked;
                }""")

                # Legacy fallback buttons
                legacy_reply_sel = (
                    "button[aria-label*='Load previous replies'], "
                    "button[aria-label*='View replies'], "
                    "button[aria-label*='load previous replies'], "
                    "button[aria-label*='view replies'], "
                    "button[aria-label*='Show previous replies']"
                )
                with contextlib.suppress(Exception):
                    for btn in await self.page.locator(legacy_reply_sel).all():
                        if await btn.is_visible(timeout=200):
                            await btn.click(timeout=1_000)
                            clicked_count += 1

                if clicked_count == 0:
                    break
                await asyncio.sleep(1.0)

            # ── Step 3: expand truncated comment bodies ("… more") ───────────
            await self.page.evaluate("""() => {
                document.querySelectorAll('button, span[role="button"]').forEach(b => {
                    const txt = (b.innerText || '').trim();
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    if (txt === '… more' || txt === 'more' || txt.endsWith('more') || aria.includes('see more')) {
                        try { b.click(); } catch(e) {}
                    }
                });
            }""")

            # Also check legacy see-more buttons
            see_more_sel = (
                "article.comments-comment-entity button.comments-comment-item__see-more-less-toggle, "
                "article.comments-comment-entity button[aria-label*='see more'], "
                "article.comments-comment-entity button[aria-label*='See more']"
            )
            for button in await self.page.locator(see_more_sel).all():
                with contextlib.suppress(Exception):
                    if await button.is_visible(timeout=300):
                        await button.click(timeout=2_000)

            # ── Step 4: extract all visible comments + replies from DOM ───────
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
            raise

        return collected[:max_per_post]

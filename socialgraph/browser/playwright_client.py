"""Playwright-based browser automation for LinkedIn saved posts refresh."""
from __future__ import annotations

from typing import Any

import structlog

from socialgraph.config.settings import Settings

logger = structlog.get_logger(__name__)

# Inject into page to collect all saved posts via Voyager API
EXTRACT_SAVED_POSTS_JS = r"""
async () => {
    const csrf = document.cookie
        .split("; ")
        .find(r => r.startsWith("JSESSIONID="))
        ?.split("=")[1]
        ?.replace(/"/g, "");
    if (!csrf) return { error: "CSRF token not found" };

    function findPosts(obj, results = []) {
        if (!obj || typeof obj !== "object") return results;
        if (obj.summary?.text && obj.trackingUrn) {
            results.push({
                author: obj.title?.text || null,
                subtitle: obj.primarySubtitle?.text || null,
                date: obj.secondarySubtitle?.text || null,
                content: obj.summary.text,
                urn: obj.trackingUrn
            });
        }
        if (Array.isArray(obj)) { obj.forEach(x => findPosts(x, results)); }
        else { Object.values(obj).forEach(x => findPosts(x, results)); }
        return results;
    }

    const raw = performance.getEntries()
        .find(x => x.name.includes("SEARCH_MY_ITEMS_SAVED_POSTS"))?.name;
    if (!raw) return { error: "No saved posts API URL in performance entries. Navigate to /my-items/saved-posts/ first." };

    // raw is already the full absolute URL — do not prepend the domain again
    const baseUrl = raw.replace("mark_bigpipe_", "").replace("_start", "");

    let allPosts = [], seenUrns = new Set(), start = 0, paginationToken = null;

    while (true) {
        let url = baseUrl.replace(/start:\d+/, `start:${start}`);
        if (paginationToken) {
            url = url.includes("paginationToken:")
                ? url.replace(/paginationToken:[^,)\s]+/, `paginationToken:${paginationToken}`)
                : url.replace("query:(", `paginationToken:${paginationToken},query:(`);
        }

        const res = await fetch(url, {
            credentials: "include",
            headers: {
                "csrf-token": csrf,
                "accept": "application/json",
                "x-restli-protocol-version": "2.0.0"
            }
        });
        if (!res.ok) break;

        const json = await res.json();
        const posts = findPosts(json);
        let newCount = 0;
        for (const p of posts) {
            if (!seenUrns.has(p.urn)) { seenUrns.add(p.urn); allPosts.push(p); newCount++; }
        }

        const nextToken = json?.data?.searchDashClustersByAll?.metadata?.paginationToken
            || json?.data?.data?.searchDashClustersByAll?.metadata?.paginationToken;

        if (!nextToken || newCount === 0) break;
        paginationToken = nextToken;
        start += 10;

        await new Promise(r => setTimeout(r, 1500));
    }

    // ── Stage 2: Hydrate reposts to recover original post content ────────────
    // Try to discover the feed queryId from already-captured network requests;
    // fall back to a known-good hardcoded value.
    const feedQueryId = performance.getEntries()
        .flatMap(e => { try { return [new URL(e.name)]; } catch { return []; } })
        .filter(u => u.pathname.includes("voyager/api/graphql"))
        .map(u => u.searchParams.get("queryId"))
        .find(q => q && q.startsWith("voyagerFeedDashUpdates"))
        || "voyagerFeedDashUpdates.ca43379417f0bcc4a7e2031d6c063250";

    function isLikelyRepost(post) {
        return (post.date && post.date.includes("Reposted")) ||
               (typeof post.content === "string" && post.content.trim().length < 50);
    }

    function extractOriginals(data, wrapperUrn) {
        const found = [];
        function walk(obj) {
            if (!obj || typeof obj !== "object") return;
            const urn = obj.entityUrn || obj.trackingUrn;
            if (urn && urn.startsWith("urn:li:activity:") && urn !== wrapperUrn) {
                const content = obj.commentary?.text?.text || obj.summary?.text || null;
                const author = obj.actor?.name?.text || obj.title?.text || null;
                if (content) found.push({ urn, content, author });
            }
            if (Array.isArray(obj)) obj.forEach(walk);
            else Object.values(obj).forEach(walk);
        }
        walk(data);
        return found;
    }

    for (let i = 0; i < allPosts.length; i++) {
        const post = allPosts[i];
        if (!isLikelyRepost(post)) continue;
        try {
            const params = new URLSearchParams();
            params.set("variables",
                `(commentsCount:0,likesCount:0,includeCommentsFirstReply:false,` +
                `includeReactions:false,moduleKey:feed-item:desktop,urnOrNss:${post.urn})`);
            params.set("queryId", feedQueryId);
            const resp = await fetch(
                "https://www.linkedin.com/voyager/api/graphql?" + params.toString(),
                {
                    credentials: "include",
                    headers: {
                        "csrf-token": csrf,
                        "accept": "application/json",
                        "x-restli-protocol-version": "2.0.0"
                    }
                }
            );
            if (!resp.ok) continue;
            const data = await resp.json();
            const originals = extractOriginals(data, post.urn);
            if (originals.length > 0) {
                // Use the last (deepest/most-original) activity found
                const orig = originals[originals.length - 1];
                allPosts[i] = {
                    ...post,
                    author: orig.author || post.author,
                    content: orig.content,
                    repost_author: post.author,
                    repost_commentary: post.content || null,
                    original_urn: orig.urn,
                    is_repost: true
                };
            }
        } catch (_) { /* skip failed hydrations */ }
        await new Promise(r => setTimeout(r, 400));
    }

    return allPosts;
}
"""


class PlaywrightClient:
    """Context manager wrapping a Playwright browser for LinkedIn automation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pw = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> PlaywrightClient:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self._settings.playwright_headless
        )
        self._context = await self._browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def new_page(self):
        assert self._context is not None, "PlaywrightClient not started"
        return await self._context.new_page()

    async def login_linkedin(self) -> None:
        """Log in to LinkedIn. Credentials read from settings (never logged)."""
        page = await self.new_page()
        await page.goto("https://www.linkedin.com/login")
        # Support both old form (session_key) and new form (username/email)
        email_selector = (
            'input[name="session_key"], input#username, '
            'input[autocomplete="username"], input[type="email"]'
        )
        await page.wait_for_selector(email_selector, timeout=15_000)
        await page.fill(email_selector, self._settings.linkedin_email)
        password_selector = (
            'input[name="session_password"], input#password, '
            'input[autocomplete="current-password"], input[type="password"]'
        )
        await page.fill(password_selector, self._settings.linkedin_password)
        await page.click('button[type="submit"]')
        # Wait until redirected away from the login page
        await page.wait_for_function(
            "() => !window.location.href.includes('/login')",
            timeout=30_000,
        )
        # Log domain only — never the full email
        logger.info(
            "linkedin.login_success",
            domain=self._settings.linkedin_email.split("@")[-1] if "@" in self._settings.linkedin_email else "unknown",
        )
        return page

    async def fetch_saved_posts(self) -> list[dict]:
        """Log in, navigate to saved posts, and extract via injected JS."""
        import asyncio

        page = await self.login_linkedin()

        # Intercept the Voyager saved-posts API response so we know the URL
        # is captured in performance.getEntries() before we run the JS.
        voyager_fired = asyncio.Event()

        def _on_response(response) -> None:
            if "SEARCH_MY_ITEMS_SAVED_POSTS" in response.url or (
                "my-items" in response.url and "savedPosts" in response.url
            ):
                voyager_fired.set()

        page.on("response", _on_response)

        await page.goto(
            "https://www.linkedin.com/my-items/saved-posts/",
            wait_until="domcontentloaded",
            timeout=30_000,
        )

        # Wait up to 15 s for Voyager API; fall through gracefully if it doesn't fire
        try:
            await asyncio.wait_for(voyager_fired.wait(), timeout=15)
            logger.info("linkedin.voyager_detected")
        except asyncio.TimeoutError:
            logger.warning("linkedin.voyager_timeout", msg="Voyager API not detected, proceeding anyway")

        # Small pause so the URL is fully registered in performance entries
        await asyncio.sleep(2)

        result = await page.evaluate(EXTRACT_SAVED_POSTS_JS)
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(f"LinkedIn JS extraction failed: {result['error']}")
        logger.info("linkedin.playwright_extracted", count=len(result))
        return result

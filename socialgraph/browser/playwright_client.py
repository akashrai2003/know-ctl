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
    // Discover the GraphQL queryId from already-captured network requests as a fallback.
    const gqlQueryId = performance.getEntries()
        .flatMap(e => { try { return [new URL(e.name)]; } catch { return []; } })
        .filter(u => u.pathname.includes("voyager/api/graphql"))
        .map(u => u.searchParams.get("queryId"))
        .find(q => q && q.startsWith("voyagerFeedDashUpdates"))
        || null;

    function isLikelyRepost(post) {
        // Only trigger on posts LinkedIn explicitly marks as reposts.
        // Removed the content-length fallback — it caused false positives.
        return post.date && post.date.includes("Reposted");
    }

    // Match only post-type URNs (activity, share, ugcPost) — not member/profile/etc.
    function isPostUrn(urn) {
        return typeof urn === "string" && (
            urn.startsWith("urn:li:activity:") ||
            urn.startsWith("urn:li:share:") ||
            urn.startsWith("urn:li:ugcPost:")
        );
    }

    // Extract a clean post URN from a compound like urn:li:fs_feedUpdate:(V2,urn:li:activity:xxx)
    function extractPostUrn(urn) {
        if (!urn) return null;
        if (isPostUrn(urn)) return urn;
        const m = urn.match(/urn:li:(?:activity|share|ugcPost):[^,)]+/);
        return m ? m[0] : null;
    }

    // Primary path: REST /voyager/api/feed/updates/{urn} exposes resharedUpdate directly
    function getOriginalFromRest(data) {
        const update = data?.value?.["com.linkedin.voyager.feed.render.UpdateV2"];
        if (!update?.resharedUpdate) return null;
        // resharedUpdate may itself be wrapped in a type key or be the object directly
        const inner = update.resharedUpdate?.["com.linkedin.voyager.feed.render.UpdateV2"]
            || update.resharedUpdate;
        const content =
            inner?.commentary?.text?.text ||
            inner?.commentary?.text ||
            inner?.socialContent?.description?.text ||
            null;
        if (!content) return null;
        const rawUrn = inner?.dashEntityUrn || inner?.entityUrn || null;
        const urn = extractPostUrn(rawUrn);
        const author = inner?.actor?.name?.text || inner?.actor?.name || null;
        return { urn, content, author };
    }

    // Fallback: tree-walk restricted to post-type URNs
    function extractOriginalsFallback(data, wrapperUrn) {
        const found = [];
        const seen = new Set();
        function walk(obj) {
            if (!obj || typeof obj !== "object") return;
            const urn = obj.entityUrn || obj.trackingUrn;
            if (urn && isPostUrn(urn) && urn !== wrapperUrn && !seen.has(urn)) {
                const content =
                    obj.commentary?.text?.text ||
                    obj.commentary?.text ||
                    obj.summary?.text ||
                    obj.description?.text ||
                    null;
                const author =
                    obj.actor?.name?.text ||
                    obj.actor?.name ||
                    obj.title?.text ||
                    null;
                if (content) {
                    seen.add(urn);
                    found.push({ urn, content, author });
                }
            }
            if (Array.isArray(obj)) obj.forEach(walk);
            else {
                try { Object.values(obj).forEach(walk); } catch (_) {}
            }
        }
        walk(data);
        return found;
    }

    const hydrationErrors = [];

    for (let i = 0; i < allPosts.length; i++) {
        const post = allPosts[i];
        if (!isLikelyRepost(post)) continue;

        let data = null;
        let errMsg = null;

        // Primary: REST feed endpoint — stable, no queryId required
        try {
            const restResp = await fetch(
                `https://www.linkedin.com/voyager/api/feed/updates/${encodeURIComponent(post.urn)}?moduleKey=feed-item%3Adesktop`,
                {
                    credentials: "include",
                    headers: {
                        "csrf-token": csrf,
                        "accept": "application/json",
                        "x-restli-protocol-version": "2.0.0"
                    }
                }
            );
            if (restResp.ok) {
                data = await restResp.json();
            } else {
                errMsg = `REST:${restResp.status}`;
            }
        } catch (e) {
            errMsg = `REST:err:${e.message}`;
        }

        // Fallback: GraphQL (requires valid queryId captured from page)
        if (!data && gqlQueryId) {
            try {
                const params = new URLSearchParams();
                params.set("variables",
                    `(commentsCount:0,likesCount:0,includeCommentsFirstReply:false,` +
                    `includeReactions:false,moduleKey:feed-item:desktop,urnOrNss:${post.urn})`);
                params.set("queryId", gqlQueryId);
                const gqlResp = await fetch(
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
                if (gqlResp.ok) {
                    data = await gqlResp.json();
                    errMsg = null;
                } else {
                    errMsg = (errMsg ? errMsg + ", " : "") + `GQL:${gqlResp.status}`;
                }
            } catch (e) {
                errMsg = (errMsg ? errMsg + ", " : "") + `GQL:err:${e.message}`;
            }
        }

        if (!data) {
            hydrationErrors.push({ urn: post.urn, error: errMsg || "no_data" });
            await new Promise(r => setTimeout(r, 400));
            continue;
        }

        // Try direct resharedUpdate path first, then fall back to tree walk
        const orig = getOriginalFromRest(data)
            || extractOriginalsFallback(data, post.urn).pop()
            || null;

        if (orig) {
            const commentary = post.content && post.content.trim()
                ? post.content.trim()
                : null;
            // Include original author attribution so both voices are visible in the note
            const origHeader = orig.author ? `**${orig.author}** originally wrote:\n` : "";
            const combinedContent = commentary
                ? `${commentary}\n\n---\n\n${origHeader}${orig.content}`
                : `${origHeader}${orig.content}`;
            allPosts[i] = {
                ...post,
                author: orig.author || post.author,
                content: combinedContent,
                repost_author: post.author,
                repost_commentary: commentary,
                original_urn: orig.urn,
                is_repost: true
            };
        } else {
            hydrationErrors.push({ urn: post.urn, error: "no_originals_found" });
        }

        await new Promise(r => setTimeout(r, 400));
    }

    return { posts: allPosts, hydrationErrors };
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
        # Support both old form (session_key) and new form (username/email).
        # Use state="attached" — the input resolves in the DOM but LinkedIn's CSS
        # may mark it not-visible during initial render, causing fill() to time out.
        email_selector = (
            'input[name="session_key"], input#username, '
            'input[autocomplete="username"], input[type="email"]'
        )
        await page.wait_for_selector(email_selector, state="attached", timeout=15_000)
        # Fill via JS to bypass visibility check (element is attached but React hides it briefly)
        await page.evaluate(
            """([sel, val]) => {
                const el = document.querySelector(sel);
                if (el) { el.value = val; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }
            }""",
            ['input[autocomplete="username"],input[name="session_key"],input#username,input[type="email"]'.split(",")[0], self._settings.linkedin_email]
        )
        # Also try direct locator fill in case React needs it for state sync
        try:
            await page.locator(email_selector).first.fill(self._settings.linkedin_email, timeout=5_000)
        except Exception:
            pass  # JS fill above is sufficient
        password_selector = (
            'input[name="session_password"], input#password, '
            'input[autocomplete="current-password"], input[type="password"]'
        )
        await page.evaluate(
            """([sel, val]) => {
                const el = document.querySelector(sel);
                if (el) { el.value = val; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }
            }""",
            ['input[autocomplete="current-password"],input[name="session_password"],input#password'.split(",")[0], self._settings.linkedin_password]
        )
        try:
            await page.locator(password_selector).first.fill(self._settings.linkedin_password, timeout=5_000)
        except Exception:
            pass
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
        # New return format: {posts: [...], hydrationErrors: [...]}
        if isinstance(result, dict) and "posts" in result:
            posts = result["posts"]
            errors = result.get("hydrationErrors", [])
            if errors:
                logger.warning(
                    "linkedin.hydration_errors",
                    count=len(errors),
                    samples=[e["urn"] + ": " + e["error"] for e in errors[:5]],
                )
            logger.info("linkedin.playwright_extracted", count=len(posts))
            return posts
        # Legacy: plain list
        logger.info("linkedin.playwright_extracted", count=len(result))
        return result

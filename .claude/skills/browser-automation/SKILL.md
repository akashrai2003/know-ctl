---
name: browser-automation
description: Playwright-based browser automation for social media post extraction. Covers playwright-mcp vs direct Playwright async API, .env credential safety, page.evaluate() for JS script injection, LinkedIn SPA navigation, headless config, and session persistence.
origin: social-graph
---

# Browser Automation

Use this skill when writing Playwright-based automation for LinkedIn (or future social platforms).

## Two Playwright Contexts — Use the Right One

| Context | When to Use |
|---------|------------|
| **Direct Playwright async API** | Pipeline automation: headless login, script injection, content extraction |
| **playwright-mcp** | Agent tool calls where an AI agent needs to interact with a browser interactively |

Default to direct Playwright async API for all pipeline code. playwright-mcp is for MCP-connected agent workflows.

---

## Security Rules (Non-Negotiable)

1. **Never log credentials.** `settings.linkedin_email` and `settings.linkedin_password` must never appear in logs, error messages, or stack traces.
2. **Credentials only from `.env`.** Never hardcode. Read via `Settings.linkedin_email` / `Settings.linkedin_password`.
3. **No screenshots of login forms.** If taking debug screenshots, do so only after the login page has completed.
4. **Headless by default.** `PLAYWRIGHT_HEADLESS=true` in `.env`. Only set to `false` for local debugging.
5. **Context isolation.** Each run uses a fresh browser context or a persisted but encrypted storage state. Never share contexts across users.

---

## PlaywrightClient Pattern

```python
# socialgraph/browser/playwright_client.py
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

class PlaywrightClient:
    """Async Playwright wrapper for LinkedIn automation."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> "PlaywrightClient":
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
        await self._pw.stop()

    async def new_page(self) -> Page:
        assert self._context is not None
        return await self._context.new_page()
```

Usage:
```python
async with PlaywrightClient(settings) as client:
    page = await client.new_page()
    await login_linkedin(page, settings)
    posts = await extract_saved_posts(page)
```

---

## LinkedIn Login Flow

```python
async def login_linkedin(page: Page, settings: Settings) -> None:
    """Log in to LinkedIn with credentials from settings."""
    await page.goto("https://www.linkedin.com/login")
    # Wait for the form — use semantic selectors, not CSS class names
    await page.wait_for_selector('input[name="session_key"]')
    await page.fill('input[name="session_key"]', settings.linkedin_email)
    await page.fill('input[name="session_password"]', settings.linkedin_password)
    await page.click('button[type="submit"]')
    # Wait for navigation away from login page
    await page.wait_for_url(lambda url: "login" not in url, timeout=15_000)
    logger.info("linkedin.login_success", email_domain=settings.linkedin_email.split("@")[-1])
    # Note: email_domain only — never log the full email
```

---

## Saved Posts Navigation

```python
SAVED_POSTS_URL = "https://www.linkedin.com/my-items/saved-posts/"

async def navigate_to_saved_posts(page: Page) -> None:
    await page.goto(SAVED_POSTS_URL)
    # Wait for the page to load enough to have a Voyager API request in performance entries
    await page.wait_for_load_state("networkidle")
    # Verify we're on the right page
    await page.wait_for_selector('[data-test-id="saved-posts"]', timeout=10_000)
```

---

## Script Injection via `page.evaluate()`

```python
# socialgraph/browser/scripts.py — JS extraction scripts as Python string constants

EXTRACT_SAVED_POSTS_JS = """
async () => {
    const csrf = document.cookie
        .split("; ")
        .find(r => r.startsWith("JSESSIONID="))
        ?.split("=")[1]
        ?.replace(/"/g, "");

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
    if (!raw) return { error: "No saved posts API URL found in performance entries" };

    const baseUrl = "https://www.linkedin.com" +
        raw.replace("mark_bigpipe_", "").replace("_start", "");

    let allPosts = [], seenUrns = new Set(), start = 0, paginationToken = null;

    while (true) {
        let url = baseUrl.replace(/start:\\d+/, `start:${start}`);
        if (paginationToken) {
            url = url.includes("paginationToken:")
                ? url.replace(/paginationToken:[^,)\\s]+/, `paginationToken:${paginationToken}`)
                : url.replace("query:(", `paginationToken:${paginationToken},query:(`);
        }

        const res = await fetch(url, {
            credentials: "include",
            headers: { "csrf-token": csrf, "accept": "application/json", "x-restli-protocol-version": "2.0.0" }
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

        await new Promise(r => setTimeout(r, 1500)); // rate limit: 1.5s between pages
    }

    return allPosts;
}
"""
```

Invoke with:
```python
posts = await page.evaluate(EXTRACT_SAVED_POSTS_JS)
if isinstance(posts, dict) and "error" in posts:
    raise ExtractionError(posts["error"])
```

---

## Post URL Navigation (for enrichment)

```python
async def navigate_post(page: Page, urn: str) -> str:
    """Navigate to a LinkedIn post and return the rendered HTML."""
    url = f"https://www.linkedin.com/feed/update/{urn}/"
    await page.goto(url)
    # Wait for post content — not a fixed delay
    await page.wait_for_selector(".feed-shared-update-v2", timeout=15_000)
    return await page.content()
```

**Always use selector-based waits, never `await page.wait_for_timeout(n)`** — timeout waits are brittle and slow.

---

## Session Persistence (Avoid Re-Login on Every Run)

```python
STATE_FILE = Path(".socialgraph/browser_state.json")

async def save_session(context: BrowserContext) -> None:
    await context.storage_state(path=str(STATE_FILE))

async def load_session(browser: Browser) -> BrowserContext:
    if STATE_FILE.exists():
        return await browser.new_context(storage_state=str(STATE_FILE))
    return await browser.new_context()
```

Session state expires when LinkedIn invalidates the cookie. Handle `page.url.contains("login")` redirects as a signal to re-authenticate.

---

## Selector Strategy

```python
# Good: semantic / role-based selectors (resilient to CSS changes)
await page.click('button[aria-label="See more comments"]')
await page.fill('input[name="session_key"]', email)

# Bad: CSS class selectors (break on LinkedIn UI updates)
await page.click('.comments-load-more__button')  # will break
```

Use `data-test-id`, `name`, `aria-label`, `role`, and text-based selectors in that priority order.

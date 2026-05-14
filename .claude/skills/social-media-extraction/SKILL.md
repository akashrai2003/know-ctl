---
name: social-media-extraction
description: Extract saved posts from social media platforms (LinkedIn, Twitter/X, Reddit, Substack). Covers LinkedIn Voyager GraphQL API, browser-authenticated extraction via Playwright, the token-based pagination strategy, post detection in nested JSON, and the platform extension guide.
origin: social-graph
---

# Social Media Extraction

Use this skill when writing code that fetches, paginates, or parses posts from any social platform.

## Platform Support Matrix

| Platform | Primary Method | Fallback | Status |
|----------|---------------|----------|--------|
| LinkedIn | JSON import (`linkedin_saved_posts.json`) | Playwright + Voyager GraphQL | ✅ Implemented |
| Twitter/X | Twitter API v2 bookmarks | Browser automation | 🔲 Planned |
| Reddit | Reddit API saved posts (PRAW) | Web scrape | 🔲 Planned |
| Substack | RSS feed + Substack API | Web scrape | 🔲 Planned |

---

## LinkedIn — Two Extraction Paths

### Path A: JSON Import (primary — no browser needed)

The user already has `linkedin_saved_posts.json` with 1508 posts exported via the browser console script. This is the fast path for initial ingestion.

```python
# socialgraph/connectors/linkedin.py
def load_from_json(path: Path) -> list[RawPost]:
    with open(path) as f:
        data = json.load(f)
    return [
        RawPost(
            platform="linkedin",
            urn=item["urn"],
            author=item.get("author"),
            subtitle=item.get("subtitle"),
            date_raw=item.get("date"),
            content=item.get("content", ""),
            source_url=urn_to_url(item["urn"]),
        )
        for item in data
    ]
```

### Path B: Automated Browser Export (Playwright refresh path)

Uses the proven JS console script injected via `page.evaluate()`. This path is for refreshing the dataset when new posts are saved.

---

## URN → Public URL Pattern

```python
def urn_to_url(urn: str) -> str:
    """Convert LinkedIn activity URN to public post URL.

    urn:li:activity:7458137957485699072
      → https://www.linkedin.com/feed/update/urn:li:activity:7458137957485699072/
    """
    return f"https://www.linkedin.com/feed/update/{urn}/"
```

---

## LinkedIn Voyager GraphQL Endpoint

**How to discover from browser DevTools:**
1. Open LinkedIn → Saved Posts page
2. DevTools → Network → XHR/Fetch → filter by `SEARCH_MY_ITEMS_SAVED_POSTS`
3. Copy the full request URL — it contains both the endpoint and query variables

**Endpoint pattern:**
```
GET https://www.linkedin.com/voyager/api/graphql
    ?variables=(start:0,paginationToken:XXX,query:(flagshipSearchIntent:SEARCH_MY_ITEMS_SAVED_POSTS))
```

**Required request headers:**
```python
headers = {
    "csrf-token": csrf_token,        # JSESSIONID cookie value, stripped of quotes
    "accept": "application/json",
    "x-restli-protocol-version": "2.0.0",
}
# credentials="include" (browser-authenticated session required)
```

**False leads to avoid:**
- `/rest/trackMediaApi/trackMedia` → pure telemetry, discard immediately
- `/voyager/api/identity/dash/profiles/` → user profile data, unrelated to saved posts

---

## Pagination Strategy — Token-Based (CRITICAL)

LinkedIn uses **token-based pagination**. Incrementing `start` offset alone (`start=0`, `start=10`, `start=20`) returns the **same first page** every time.

Both `start` AND `paginationToken` must be updated per page.

### The proven JS loop (injected via `page.evaluate()`):

```javascript
async function exportSavedPosts() {
    const csrf = document.cookie
        .split("; ")
        .find(r => r.startsWith("JSESSIONID="))
        ?.split("=")[1]
        ?.replace(/"/g, "");

    const raw = performance.getEntries()
        .find(x => x.name.includes("SEARCH_MY_ITEMS_SAVED_POSTS"))?.name;
    const baseUrl = "https://www.linkedin.com" +
        raw.replace("mark_bigpipe_", "").replace("_start", "");

    let allPosts = [], seenUrns = new Set(), start = 0, paginationToken = null;

    while (true) {
        let url = baseUrl.replace(/start:\d+/, `start:${start}`);
        if (paginationToken) {
            if (url.includes("paginationToken:")) {
                url = url.replace(/paginationToken:[^,)\s]+/, `paginationToken:${paginationToken}`);
            } else {
                url = url.replace("query:(", `paginationToken:${paginationToken},query:(`);
            }
        }

        const json = await fetch(url, {
            credentials: "include",
            headers: { "csrf-token": csrf, "accept": "application/json", "x-restli-protocol-version": "2.0.0" }
        }).then(r => r.json());

        const posts = findPosts(json);
        let newCount = 0;
        for (const post of posts) {
            if (!seenUrns.has(post.urn)) { seenUrns.add(post.urn); allPosts.push(post); newCount++; }
        }

        const nextToken = json?.data?.searchDashClustersByAll?.metadata?.paginationToken
            || json?.data?.data?.searchDashClustersByAll?.metadata?.paginationToken;

        // CORRECT termination — newCount, NOT posts.length (see bug history below)
        if (!nextToken || newCount === 0) break;

        paginationToken = nextToken;
        start += 10;
    }
    return allPosts;
}
```

### ⚠️ The Infinite-Pagination Bug — Must Not Repeat

**Wrong termination:** `if (!posts.length) break`

**Why it fails:** Recursive object traversal (`findPosts`) finds valid-looking objects even in empty shell responses. At 46,000+ iterations, the loop was still running.

**Root cause:** `posts.length > 0` does not mean *new* posts — just that the response contains objects matching the detection signature.

**Correct fix:** Track unique URNs in a `seenUrns` Set. Terminate when `newCount === 0` (no new unseen URNs on this page) **or** when `nextToken` is null.

---

## Post Object Detection (Recursive JSON Traversal)

LinkedIn buries post objects deeply in a nested GraphQL response. The reliable signature is:

```python
def find_posts(obj: Any, results: list | None = None) -> list[dict]:
    """Recursively find post objects in LinkedIn API response."""
    if results is None:
        results = []
    if not obj or not isinstance(obj, (dict, list)):
        return results
    if isinstance(obj, dict):
        # Signature: has summary.text AND trackingUrn
        summary_text = (obj.get("summary") or {}).get("text")
        urn = obj.get("trackingUrn")
        if summary_text and urn:
            results.append({
                "author": (obj.get("title") or {}).get("text"),
                "subtitle": (obj.get("primarySubtitle") or {}).get("text"),
                "date": (obj.get("secondarySubtitle") or {}).get("text"),
                "content": summary_text,
                "urn": urn,
            })
        for v in obj.values():
            find_posts(v, results)
    elif isinstance(obj, list):
        for item in obj:
            find_posts(item, results)
    return results
```

---

## Rate Limiting

LinkedIn does not publish rate limits. Use conservative back-off:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

RATE_LIMIT_DELAY = 1.5  # seconds between pages

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=60))
async def fetch_page(session: httpx.AsyncClient, url: str, headers: dict) -> dict:
    resp = await session.get(url, headers=headers)
    if resp.status_code == 429:
        raise RateLimitError("LinkedIn rate limited")
    resp.raise_for_status()
    return resp.json()
```

---

## Adding a New Platform

1. Create `socialgraph/connectors/{platform}.py`
2. Implement `BaseConnector` from `socialgraph/connectors/base.py`
3. Required: `async def fetch_saved_posts() -> AsyncIterator[RawPost]`
4. Register in `socialgraph/connectors/__init__.py`
5. Add auth env vars to `.env.example`
6. Add row to the support matrix at the top of this file
7. Write integration test: `tests/integration/test_{platform}_connector.py`

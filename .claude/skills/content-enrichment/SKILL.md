---
name: content-enrichment
description: Enrich social media posts by following external links, extracting article text with trafilatura, harvesting notable comments, and deduplicating URLs across posts. Covers URL filtering, fetch_status lifecycle, BeautifulSoup fallback, and comment-URL flagging.
origin: social-graph
---

# Content Enrichment

Use this skill when writing code that follows external links from posts, extracts article content, or processes comments.

## Enrichment Scope per Post

| Item | Action |
|------|--------|
| External links in post body | Follow 1 level deep; extract title, description, body excerpt |
| Top-5 comments | Store comment text; flag if contains an external URL |
| Author profile | Extract author headline from post metadata only (no profile page visit) |
| Images/videos | Record URL in `ExternalLink` with `content_type="media"` but do NOT download |

---

## URL Filtering — What to Skip

```python
BLOCKED_URL_PATTERNS = [
    "linkedin.com",
    "twitter.com",
    "x.com",
    "t.co",              # Twitter short links (loop)
    "facebook.com",
    "instagram.com",
    "lnkd.in",           # LinkedIn shortener (self-referential)
    "mailto:",
    "tel:",
    "javascript:",
    ".gif",              # tracking pixels
    ".png?",             # tracking pixels with query params
]

BLOCKED_URL_PREFIXES = ["#"]   # anchor-only links

def should_fetch_url(url: str) -> bool:
    url_lower = url.lower().strip()
    if any(url_lower.startswith(p) for p in BLOCKED_URL_PREFIXES):
        return False
    if any(blocked in url_lower for blocked in BLOCKED_URL_PATTERNS):
        return False
    if not url_lower.startswith("http"):
        return False
    return True
```

---

## Content Extraction Priority

1. **trafilatura** — best for article/blog content; extracts readable text, strips nav/ads
2. **BeautifulSoup fallback** — for sites trafilatura can't handle (SPAs, paywalls, etc.)

```python
import trafilatura
from bs4 import BeautifulSoup

async def extract_url_content(url: str, html: bytes) -> ExternalLinkContent:
    """Extract readable content from raw HTML."""
    # Try trafilatura first
    text = trafilatura.extract(html, include_comments=False, include_tables=False)
    if text and len(text) > 100:
        return ExternalLinkContent(
            title=_extract_title(html),
            description=_extract_og_description(html),
            body_excerpt=text[:2000],
            method="trafilatura",
        )
    # Fallback: BeautifulSoup for title + og:description only
    soup = BeautifulSoup(html, "lxml")
    title = soup.find("title")
    og_desc = soup.find("meta", property="og:description")
    return ExternalLinkContent(
        title=title.text.strip() if title else None,
        description=og_desc["content"].strip() if og_desc and og_desc.get("content") else None,
        body_excerpt=None,
        method="bs4_fallback",
    )
```

---

## HTTP Fetching with Safety Limits

```python
FETCH_TIMEOUT = 10.0   # seconds per URL
MAX_RESPONSE_BYTES = 2_000_000   # 2MB cap — avoid downloading large files

async def fetch_url_safe(client: httpx.AsyncClient, url: str) -> bytes | None:
    """Fetch URL with size and timeout limits."""
    try:
        async with client.stream("GET", url, timeout=FETCH_TIMEOUT, follow_redirects=True) as resp:
            if resp.status_code != 200:
                return None
            content_type = resp.headers.get("content-type", "")
            if not any(ct in content_type for ct in ["text/html", "text/plain", "application/xhtml"]):
                return None   # skip binary, JSON APIs, etc.
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes(chunk_size=8192):
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    break
            return b"".join(chunks)
    except Exception as exc:
        logger.warning("url_fetch_failed", url=url, error=str(exc))
        return None
```

---

## URL Deduplication (Cross-Post)

The same URL may appear in multiple posts. Fetch it once; share the `ExternalLink.id`.

```python
# In repo layer — check before inserting:
async def get_or_create_external_link(
    session: AsyncSession, url: str
) -> ExternalLink:
    existing = await session.scalar(
        select(ExternalLink).where(ExternalLink.url == url)
    )
    if existing:
        return existing
    new_link = ExternalLink(url=url, fetch_status="pending")
    session.add(new_link)
    return new_link
```

---

## Fetch Status Lifecycle

```
pending → fetching → ok
                   → failed
                   → skipped
```

- `pending`: URL discovered but not yet processed
- `fetching`: in-flight (set before starting; ensures crash recovery re-tries)
- `ok`: content successfully extracted; `body_excerpt`, `title`, `description` populated
- `failed`: fetch errored or returned non-200; set `error_reason`; pipeline continues
- `skipped`: URL matched `BLOCKED_URL_PATTERNS`; not fetched

```python
async def enrich_link(session: AsyncSession, link: ExternalLink, client: httpx.AsyncClient) -> None:
    link.fetch_status = "fetching"
    await session.flush()   # write "fetching" immediately for crash safety
    html = await fetch_url_safe(client, link.url)
    if html is None:
        link.fetch_status = "failed"
        link.error_reason = "no_response"
        return
    content = await extract_url_content(link.url, html)
    link.title = content.title
    link.description = content.description
    link.body_excerpt = content.body_excerpt
    link.fetch_status = "ok"
    link.fetched_at = datetime.utcnow()
```

---

## Comment Processing

```python
# Store top-N comments per post (N = SG_MAX_COMMENTS, default 5)

def process_comments(raw_comments: list[dict], max_n: int = 5) -> list[CommentData]:
    """Extract comment text and flag external URLs."""
    comments: list[CommentData] = []
    for raw in raw_comments[:max_n]:
        text = raw.get("commentary", {}).get("text", "")
        urls = _extract_urls(text)
        comments.append(CommentData(
            text=text,
            author=raw.get("commenterName"),
            has_external_url=bool(urls and any(should_fetch_url(u) for u in urls)),
            external_urls=urls,
        ))
    return comments
```

If `comments_notable=True` (any comment has external URL), the graph agent will add an edge from the post node to the linked URL node with relation `cites` and confidence `AMBIGUOUS`.

---

## Enrichment Agent Batch Pattern

```python
async def enrich_posts_batch(
    posts: list[Post],
    repo: Repo,
    settings: Settings,
) -> list[Post]:
    """Enrich all posts — fetch URLs and process comments in parallel."""
    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (compatible; SocialGraphBot/1.0)"},
        timeout=FETCH_TIMEOUT,
    ) as client:
        tasks = [enrich_single_post(post, repo, client) for post in posts]
        return await asyncio.gather(*tasks, return_exceptions=False)
```

Never open a new `httpx.AsyncClient` per URL — create one client per batch and share it.

---

## What NOT to Enrich

- **Images** from posts → record URL only, no download
- **Video content** → record URL only
- **Profile pages** of authors → use data from post metadata only
- **Already-fetched URLs** (status `ok`) → skip in subsequent pipeline runs
- **LinkedIn internal pages** → always skip (in `BLOCKED_URL_PATTERNS`)

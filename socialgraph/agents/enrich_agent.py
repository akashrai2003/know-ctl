"""Enrich agent: fetch external URLs, extract content, process comments."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog
import trafilatura
from bs4 import BeautifulSoup
from playwright.async_api import Browser, async_playwright
from sqlalchemy import select, update

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.storage.enums import FetchStatus, PostStatus
from socialgraph.storage.models import ExternalLink, Post, PostExternalLink
from socialgraph.storage.repo import Repo

UTC = timezone.utc

if TYPE_CHECKING:
    from socialgraph.llm.router import LLMRouter

logger = structlog.get_logger(__name__)

FETCH_TIMEOUT = 10.0
MAX_RESPONSE_BYTES = 2_000_000
CONCURRENCY = 10
PW_CONCURRENCY = 3  # Max concurrent Playwright fetches (browser tabs)

# Errors that Playwright (real browser) may recover from
PLAYWRIGHT_RETRYABLE_ERRORS = {"http_403", "http_406", "http_999", "http_500"}

# Selectors tried in order to dismiss cookie/signup modals before extracting
POPUP_DISMISS_SELECTORS = [
    "[aria-label='Close']",
    "[aria-label='close']",
    "button[aria-label='Close']",
    "#onetrust-accept-btn-handler",
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    "button:has-text('Accept cookies')",
    "button:has-text('I Accept')",
    "button:has-text('I agree')",
    "button:has-text('No thanks')",
    "button:has-text('Not now')",
    "button:has-text('Reject all')",
    "button:has-text('Continue reading')",
    "[data-testid='close-button']",
    # X.com login prompt bar
    "[data-testid='sheetDialog'] [aria-label='Close']",
    "[data-testid='xMigrationBottomBar'] button",
]

BLOCKED_URL_PATTERNS = [
    "linkedin.com",  # feed/profile pages — not articles (lnkd.in is allowed)
    "twitter.com",
    "x.com",
    "t.co",
    "facebook.com",
    "instagram.com",
]

# Strip trailing punctuation that regex grabs from sentence context
_URL_TRAIL_RE = re.compile(r"[)\].,;:!?\"']+$")
URL_RE = re.compile(r"https?://[^\s\"'<>]+")
GITHUB_REPO_RE = re.compile(r"https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s?#]+)")
# colab.research.google.com/github/<user>/<repo>/blob/<branch>/<path/to/notebook.ipynb>
COLAB_GITHUB_RE = re.compile(
    r"https?://colab\.research\.google\.com/github/([^/]+)/([^/]+)/blob/([^/]+)/(.+\.ipynb)"
)


def should_fetch_url(url: str) -> bool:
    u = url.lower().strip()
    if not u.startswith("http"):
        return False
    return not any(p in u for p in BLOCKED_URL_PATTERNS)


def _extract_urls(text: str) -> list[str]:
    raw = URL_RE.findall(text)
    cleaned: list[str] = []
    seen: set[str] = set()
    for u in raw:
        u = _URL_TRAIL_RE.sub("", u)  # strip trailing ),. etc.
        if u and u not in seen:
            seen.add(u)
            cleaned.append(u)
    return cleaned


class EnrichAgent:
    name = "enrich"

    def __init__(self, router: LLMRouter | None = None) -> None:
        self._router = router

    async def run(self, ctx: StageContext) -> StageOutput:
        # Run on all posts that have actual content (not just newly ingested ones)
        result = await ctx.db.scalars(select(Post).where(Post.status.in_(["ingested", "pending"])))
        posts = list(result.all())

        repo = Repo(ctx.db)
        semaphore = asyncio.Semaphore(CONCURRENCY)
        # Serialise all DB writes — prevents concurrent ORM autoflush races
        # that leave links stuck in "fetching" state.
        db_sem = asyncio.Semaphore(1)
        processed = failed = 0

        # Reset any links stuck in "fetching" from a previous interrupted run
        await ctx.db.execute(
            update(ExternalLink)
            .where(ExternalLink.fetch_status == FetchStatus.FETCHING.value)
            .values(fetch_status=FetchStatus.PENDING.value)
        )

        # Reset junk entries so they get a fresh fetch (Colab→notebook, etc.)
        junk_result = await ctx.db.scalars(
            select(ExternalLink).where(
                ExternalLink.fetch_status == FetchStatus.OK.value,
                ExternalLink.body_excerpt.isnot(None),
            )
        )
        junk_reset = 0
        for lnk in junk_result.all():
            if _is_junk_content(lnk.body_excerpt, lnk.title):
                lnk.fetch_status = FetchStatus.PENDING.value
                lnk.error_reason = None
                lnk.body_excerpt = None
                lnk.ai_summary = None
                junk_reset += 1
        if junk_reset:
            logger.info("enrich.junk_reset", count=junk_reset)

        # Reset retryable failed URLs — Playwright may succeed where httpx couldn't
        failed_result = await ctx.db.scalars(
            select(ExternalLink).where(ExternalLink.fetch_status == FetchStatus.FAILED.value)
        )
        retryable_reset = 0
        for lnk in failed_result.all():
            err = lnk.error_reason or ""
            if (
                err in PLAYWRIGHT_RETRYABLE_ERRORS
                or err == ""
                or err.startswith("[SSL:")
                or err.startswith("SSL:")
                or err.startswith("Server disconnected")
            ):
                lnk.fetch_status = FetchStatus.PENDING.value
                lnk.error_reason = None
                retryable_reset += 1

        if retryable_reset:
            logger.info("enrich.retryable_reset", count=retryable_reset)

        await ctx.db.commit()

        # Existing completed posts can still contain a body link reset above.
        # Pull only those affected posts back into the fetch pass without
        # reprocessing every completed post on each incremental run.
        pending_rows = await ctx.db.scalars(
            select(Post)
            .join(PostExternalLink, PostExternalLink.post_id == Post.id)
            .join(ExternalLink, ExternalLink.id == PostExternalLink.external_link_id)
            .where(
                PostExternalLink.context == "body",
                ExternalLink.fetch_status == FetchStatus.PENDING.value,
            )
            .distinct()
        )
        known_ids = {post.id for post in posts}
        posts.extend(post for post in pending_rows.all() if post.id not in known_ids)

        if posts:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                pw_sem = asyncio.Semaphore(PW_CONCURRENCY)

                async with httpx.AsyncClient(
                    timeout=FETCH_TIMEOUT,
                    headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    },
                    follow_redirects=True,
                ) as client:

                    async def enrich_one(post: Post) -> None:
                        nonlocal processed, failed
                        async with semaphore:
                            try:
                                await _enrich_post(post, repo, client, browser, pw_sem, db_sem)
                                async with db_sem:
                                    post.status = PostStatus.ENRICHED.value
                                    await repo.flush()
                                processed += 1
                            except Exception as exc:
                                logger.error("enrich.post_failed", urn=post.urn, error=str(exc))
                                failed += 1

                    await asyncio.gather(*[enrich_one(p) for p in posts])

                await browser.close()

            await ctx.db.commit()

        # ── vLLM summarization pass ──────────────────────────────────────
        summarized = 0
        if self._router:
            summ_log = Path(ctx.settings.workspace_dir) / "logs" / "summarization.jsonl"
            summarized = await _summarize_links(ctx.db, self._router, summ_log)
            await ctx.db.commit()

        logger.info("enrich.complete", processed=processed, summarized=summarized, failed=failed)
        nothing_to_do = processed == 0 and failed == 0 and summarized == 0
        return StageOutput(
            stage=self.name,
            processed=processed,
            skipped=1 if nothing_to_do else 0,
            failed=failed,
            meta={"summarized": summarized},
        )


async def _enrich_post(
    post: Post,
    repo: Repo,
    client: httpx.AsyncClient,
    browser: Browser,
    pw_sem: asyncio.Semaphore,
    db_sem: asyncio.Semaphore,
) -> None:
    urls = _extract_urls(post.content or "")
    for url in urls:
        if not should_fetch_url(url):
            continue

        # --- DB: get-or-create link record (serialised) ---
        async with db_sem:
            link, _ = await repo.get_or_create_external_link(url)
            link_id = link.id
            # Fetch if newly created OR if reset to pending (e.g. after junk cleanup)
            needs_fetch = link.fetch_status == "pending"
            if needs_fetch:
                # Mark as fetching *inside* db_sem before releasing it
                link.fetch_status = "fetching"
                await repo.flush()
            await repo.link_post_to_url(post.id, link_id, context="body")

        if not needs_fetch:
            continue

        # --- HTTP: fetch outside db_sem so other tasks run concurrently ---
        data = await _resolve_and_fetch(url, client, browser, pw_sem)

        # --- DB: write results back (serialised) ---
        async with db_sem:
            lnk = await repo.get(ExternalLink, link_id)
            if lnk is None:
                continue
            lnk.fetch_status = data["fetch_status"]
            lnk.title = data.get("title")
            lnk.description = data.get("description")
            lnk.body_excerpt = data.get("body_excerpt")
            lnk.error_reason = data.get("error_reason")
            lnk.fetched_at = data.get("fetched_at")
            await repo.flush()


async def _resolve_and_fetch(
    url: str,
    client: httpx.AsyncClient,
    browser=None,
    pw_sem: asyncio.Semaphore | None = None,
    _depth: int = 0,
) -> dict:
    """Fetch a URL and return a plain dict — never touches ORM objects.

    Handles:
    - lnkd.in → LinkedIn safety interstitial → extracts real destination URL
    - github.com/{user}/{repo} → fetches README directly from raw.githubusercontent.com
    - Playwright fallback for 403/406/SSL errors and X.com JS rendering
    - Regular HTML pages → trafilatura extraction
    """
    result: dict = {
        "fetch_status": "pending",
        "title": None,
        "description": None,
        "body_excerpt": None,
        "error_reason": None,
        "fetched_at": None,
    }

    if _depth > 2:
        result["fetch_status"] = "failed"
        result["error_reason"] = "too_many_redirects"
        return result

    try:
        # ── Google Colab /github/ link → fetch raw notebook from GitHub ────
        colab_gh = COLAB_GITHUB_RE.match(url)
        if colab_gh:
            user, repo_name, branch, nb_path = colab_gh.groups()
            nb_text = await _fetch_colab_notebook(user, repo_name, branch, nb_path, client)
            if nb_text:
                result["fetch_status"] = "ok"
                result["title"] = Path(nb_path).stem.replace("-", " ").replace("_", " ").title()
                result["body_excerpt"] = nb_text
                result["fetched_at"] = datetime.now(UTC)
                return result
            # Fall through to normal fetch if notebook unavailable

        # ── GitHub repo: fetch README directly ───────────────────────────
        gh = GITHUB_REPO_RE.match(url)
        if gh:
            readme = await _fetch_github_readme(gh.group(1), gh.group(2), client)
            if readme:
                result["fetch_status"] = "ok"
                result["title"] = f"{gh.group(1)}/{gh.group(2)}"
                result["body_excerpt"] = readme
                result["fetched_at"] = datetime.now(UTC)
                return result
            # Fall through to normal fetch (repo page) if no README found

        # ── Regular HTTP fetch ────────────────────────────────────────────
        chunks: list[bytes] = []
        total = 0
        async with client.stream("GET", url) as resp:
            final_url = str(resp.url)

            if resp.status_code != 200:
                error_reason = f"http_{resp.status_code}"
                # Try Playwright before giving up on retryable errors
                if browser and pw_sem and error_reason in PLAYWRIGHT_RETRYABLE_ERRORS:
                    async with pw_sem:
                        pw_result = await _playwright_fetch(url, browser)
                    if pw_result["fetch_status"] == "ok":
                        return pw_result
                result["fetch_status"] = "failed"
                result["error_reason"] = error_reason
                return result

            ct = resp.headers.get("content-type", "")
            if not any(x in ct for x in ["text/html", "text/plain", "application/xhtml"]):
                result["fetch_status"] = "skipped"
                result["error_reason"] = f"content_type:{ct[:64]}"
                return result

            async for chunk in resp.aiter_bytes(8192):
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    break

        html = b"".join(chunks)

        # LinkedIn safety interstitial: lnkd.in returns 200 directly with safety
        # page HTML.  The real destination is in <a data-tracking-control-name=
        # "external_url_click" href="...">
        if b"external_url_click" in html:
            soup_chk = BeautifulSoup(html, "lxml")
            anchor = soup_chk.find("a", {"data-tracking-control-name": "external_url_click"})
            href = anchor.get("href") if anchor else None
            if anchor and isinstance(href, str) and href.startswith("http"):
                return await _resolve_and_fetch(href, client, browser, pw_sem, _depth + 1)
            result["fetch_status"] = "skipped"
            result["error_reason"] = "linkedin_safety_no_url"
            return result

        # Legacy redirect path: linkedin.com/safety/go?url=...
        if "linkedin.com/safety/go" in final_url:
            parsed = urllib.parse.urlparse(final_url)
            qs = urllib.parse.parse_qs(parsed.query)
            real_url = qs.get("url", [None])[0]
            if real_url:
                return await _resolve_and_fetch(real_url, client, browser, pw_sem, _depth + 1)
            result["fetch_status"] = "skipped"
            result["error_reason"] = "linkedin_safety_no_url"
            return result

        # Extract with trafilatura (best for articles/blogs)
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_precision=False,
        )

        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("title")
        og_title = soup.find("meta", {"property": "og:title"})
        og_desc = soup.find("meta", {"property": "og:description"})

        og_title_content = og_title.get("content") if og_title else None
        og_desc_content = og_desc.get("content") if og_desc else None

        title = (og_title_content.strip() if isinstance(og_title_content, str) else None) or (
            title_tag.text.strip() if title_tag else None
        )

        result["title"] = title[:512] if title else None
        result["description"] = og_desc_content[:1024] if isinstance(og_desc_content, str) else None

        # Detect junk pages before storing
        if _is_junk_content(text, title):
            result["fetch_status"] = "skipped"
            result["error_reason"] = "junk_content"
            return result

        result["body_excerpt"] = text[:5000] if text else None
        result["fetch_status"] = "ok"
        result["fetched_at"] = datetime.now(UTC)

    except Exception as exc:
        err_str = str(exc)[:256]
        # SSL errors / connection issues — Playwright may bypass them
        if (
            browser
            and pw_sem
            and ("SSL:" in err_str or "CERTIFICATE" in err_str or "certificate" in err_str)
        ):
            try:
                async with pw_sem:
                    pw_result = await _playwright_fetch(url, browser)
                if pw_result["fetch_status"] == "ok":
                    return pw_result
            except Exception:
                pass
        result["fetch_status"] = "failed"
        result["error_reason"] = err_str

    return result


async def _playwright_fetch(url: str, browser) -> dict:
    """Fetch a URL with a real Chromium browser.

    Bypasses SSL errors, renders JavaScript, dismisses cookie/signup popups,
    then extracts content via trafilatura on the fully-rendered HTML.
    """
    result: dict = {
        "fetch_status": "pending",
        "title": None,
        "description": None,
        "body_excerpt": None,
        "error_reason": None,
        "fetched_at": None,
    }
    ctx = None
    try:
        ctx = await browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()

        resp = await page.goto(url, timeout=25000, wait_until="domcontentloaded")
        if resp and resp.status not in (200, 304, 0):
            result["fetch_status"] = "failed"
            result["error_reason"] = f"http_{resp.status}"
            return result

        # Short wait for JS-rendered content to appear
        await asyncio.sleep(1.5)

        # ── Dismiss popups / cookie banners ──────────────────────────────
        for sel in POPUP_DISMISS_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click(timeout=2000)
                    await asyncio.sleep(0.4)
                    break
            except Exception:
                continue

        # Press Escape to close any remaining modal
        with contextlib.suppress(Exception):
            await page.keyboard.press("Escape")

        # JS: strip overlay/paywall elements that block content
        await page.evaluate("""() => {
            const sels = [
                '[data-testid="overflow"]',
                '.ReactModal__Overlay',
                '[class*="paywall"]', '[class*="Paywall"]',
                '[id*="paywall"]',
                '.overlay', '.modal-backdrop',
                '[class*="modal"][class*="overlay"]',
            ];
            sels.forEach(s => {
                document.querySelectorAll(s).forEach(el => el.remove());
            });
            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
        }""")

        # ── Handle lnkd.in interstitial rendered by JS ───────────────────
        html_bytes = (await page.content()).encode("utf-8", errors="replace")
        if b"external_url_click" in html_bytes:
            from bs4 import BeautifulSoup

            soup_chk = BeautifulSoup(html_bytes, "lxml")
            anchor = soup_chk.find("a", {"data-tracking-control-name": "external_url_click"})
            href = anchor.get("href") if anchor else None
            if anchor and isinstance(href, str) and href.startswith("http"):
                # Navigate to the real URL in the same tab
                resp2 = await page.goto(href, timeout=25000, wait_until="domcontentloaded")
                if resp2 and resp2.status not in (200, 304, 0):
                    result["fetch_status"] = "failed"
                    result["error_reason"] = f"http_{resp2.status}"
                    return result
                await asyncio.sleep(1.0)

        html = await page.content()

        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_precision=False,
        )

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("title")
        og_title = soup.find("meta", {"property": "og:title"})
        og_desc = soup.find("meta", {"property": "og:description"})

        og_title_content = og_title.get("content") if og_title else None
        og_desc_content = og_desc.get("content") if og_desc else None

        title = (og_title_content.strip() if isinstance(og_title_content, str) else None) or (
            title_tag.text.strip() if title_tag else None
        )

        result["title"] = title[:512] if title else None
        result["description"] = og_desc_content[:1024] if isinstance(og_desc_content, str) else None

        if _is_junk_content(text, title):
            result["fetch_status"] = "skipped"
            result["error_reason"] = "junk_content"
            return result

        result["body_excerpt"] = text[:5000] if text else None
        result["fetch_status"] = "ok"
        result["fetched_at"] = datetime.now(UTC)

    except Exception as exc:
        result["fetch_status"] = "failed"
        result["error_reason"] = f"pw:{str(exc)[:200]}"
    finally:
        if ctx:
            with contextlib.suppress(Exception):
                await ctx.close()

    return result


def _is_junk_content(text: str | None, _title: str | None) -> bool:
    """Return True if extracted content is clearly worthless and should not be summarized."""
    if not text:
        return True
    t = text.lower().strip()
    # X.com / Twitter: requires JavaScript
    if "javascript is disabled in this browser" in t:
        return True
    # YouTube footer only (nav links, no article content)
    if len(t) < 300 and "© 20" in t and "about" in t and "press" in t and "copyright" in t:
        return True
    # Login / sign-in wall: effectively no content
    return len(t) < 80


async def _fetch_colab_notebook(
    user: str, repo: str, branch: str, nb_path: str, client: httpx.AsyncClient
) -> str | None:
    """Fetch a Colab /github/ notebook and return a readable text excerpt.

    Converts the raw .ipynb JSON into plain text: markdown cells first,
    then up to 20 lines from the first code cell — enough context for summarization.
    """
    raw_url = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{nb_path}"
    try:
        resp = await client.get(raw_url)
        if resp.status_code != 200:
            return None
        nb = resp.json()
    except Exception:
        return None

    cells = nb.get("cells") or nb.get("worksheets", [{}])[0].get("cells", [])
    parts: list[str] = []
    code_included = 0
    for cell in cells:
        ct = cell.get("cell_type", "")
        src = cell.get("source") or cell.get("input", [])
        if isinstance(src, list):
            src = "".join(src)
        src = src.strip()
        if not src:
            continue
        if ct == "markdown":
            parts.append(src)
        elif ct == "code" and code_included < 2:
            # Include only the first 2 code cells, truncated
            parts.append("```\n" + "\n".join(src.splitlines()[:20]) + "\n```")
            code_included += 1
    if not parts:
        return None
    return "\n\n".join(parts)[:5000]


async def _fetch_github_readme(user: str, repo: str, client: httpx.AsyncClient) -> str | None:
    """Fetch README text from raw.githubusercontent.com, trying common branch/name combos."""
    for branch in ("main", "master"):
        for fname in ("README.md", "readme.md", "README.rst", "README"):
            url = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{fname}"
            try:
                resp = await client.get(url)
                if resp.status_code == 200 and resp.text.strip():
                    # Compact: remove excessive blank lines, cap at 5000 chars
                    lines = [ln for ln in resp.text.splitlines() if ln.strip()]
                    return "\n".join(lines)[:5000]
            except Exception:
                continue
    return None


async def _summarize_links(db, router: LLMRouter, log_path: Path) -> int:  # type: ignore[type-arg]
    """Batch-summarize all fetched ExternalLinks that have body_excerpt but no ai_summary.

    Every prompt + response is appended to log_path as JSONL for quality inspection.
    """
    from socialgraph.llm.prompts import SUMMARIZE_CONTENT_SYSTEM, SUMMARIZE_CONTENT_USER

    result = await db.scalars(
        select(ExternalLink).where(
            ExternalLink.fetch_status == FetchStatus.OK.value,
            ExternalLink.body_excerpt.isnot(None),
            ExternalLink.ai_summary.is_(None),
        )
    )

    links = list(result.all())
    if not links:
        logger.info("enrich.summarize_skip", reason="no links need summarization")
        return 0

    logger.info("enrich.summarize_start", count=len(links))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("a", encoding="utf-8")
    client = router.batch_client
    batch_size = 10
    summarized = 0

    try:
        for i in range(0, len(links), batch_size):
            batch = links[i : i + batch_size]
            messages_list = []
            for lnk in batch:
                # Send up to 4000 chars of body + prepend og:description if not already inside
                excerpt = (lnk.body_excerpt or "")[:4000]
                if lnk.description and lnk.description[:100] not in excerpt:
                    excerpt = lnk.description[:500] + "\n\n" + excerpt
                user_msg = SUMMARIZE_CONTENT_USER.format(
                    title=lnk.title or "",
                    url=lnk.url,
                    excerpt=excerpt,
                )
                messages_list.append(
                    [
                        {"role": "system", "content": SUMMARIZE_CONTENT_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ]
                )
            try:
                results = await client.batch_chat(messages_list, temperature=0.1, max_tokens=500)
                for lnk, messages, summary in zip(batch, messages_list, results, strict=False):
                    if summary and isinstance(summary, str):
                        lnk.ai_summary = summary.strip()[:2000]
                        summarized += 1
                    log_fh.write(
                        json.dumps(
                            {
                                "url": lnk.url,
                                "title": lnk.title,
                                "prompt": messages[-1]["content"],
                                "response": summary,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except Exception as exc:
                logger.error("enrich.summarize_batch_failed", batch_i=i, error=str(exc))
    finally:
        log_fh.close()

    logger.info("enrich.summarize_done", count=len(links), log=str(log_path))
    return summarized

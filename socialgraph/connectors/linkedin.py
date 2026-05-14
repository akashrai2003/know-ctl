from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import structlog

from socialgraph.connectors.base import RawPost

logger = structlog.get_logger(__name__)


def urn_to_url(urn: str) -> str:
    """Convert LinkedIn activity URN to public post URL."""
    return f"https://www.linkedin.com/feed/update/{urn}/"


def find_posts(obj: Any, results: list[dict] | None = None) -> list[dict]:
    """Recursively find post objects in a LinkedIn API response dict/list."""
    if results is None:
        results = []
    if not obj or not isinstance(obj, (dict, list)):
        return results
    if isinstance(obj, dict):
        summary_text = (obj.get("summary") or {}).get("text")
        urn = obj.get("trackingUrn")
        if summary_text and urn:
            results.append(
                {
                    "author": (obj.get("title") or {}).get("text"),
                    "subtitle": (obj.get("primarySubtitle") or {}).get("text"),
                    "date": (obj.get("secondarySubtitle") or {}).get("text"),
                    "content": summary_text,
                    "urn": urn,
                }
            )
        for v in obj.values():
            find_posts(v, results)
    elif isinstance(obj, list):
        for item in obj:
            find_posts(item, results)
    return results


def _author_slug(name: str | None) -> str:
    if not name:
        return "unknown"
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")[:80]


class LinkedInJSONConnector:
    """Load saved posts from the pre-exported linkedin_saved_posts.json file."""

    platform = "linkedin"

    def __init__(self, json_path: Path) -> None:
        self._path = json_path

    async def fetch_saved_posts(self) -> list[RawPost]:
        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)

        posts: list[RawPost] = []
        for item in data:
            urn = item.get("urn")
            if not urn:
                logger.warning("linkedin.missing_urn", item_preview=str(item)[:80])
                continue
            posts.append(
                RawPost(
                    platform="linkedin",
                    urn=urn,
                    author=item.get("author"),
                    subtitle=item.get("subtitle"),
                    date_raw=item.get("date"),
                    content=item.get("content", ""),
                    source_url=urn_to_url(urn),
                )
            )
        logger.info("linkedin.json_loaded", count=len(posts))
        return posts


class LinkedInPlaywrightConnector:
    """Extract saved posts live from LinkedIn via Playwright browser automation."""

    platform = "linkedin"

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    async def fetch_saved_posts(self) -> list[RawPost]:
        from socialgraph.browser.playwright_client import PlaywrightClient

        async with PlaywrightClient(self._settings) as client:
            raw: list[dict] = await client.fetch_saved_posts()

        posts: list[RawPost] = []
        seen: set[str] = set()
        for item in raw:
            urn = item.get("urn")
            if not urn or urn in seen:
                logger.warning("linkedin.missing_or_dup_urn", item_preview=str(item)[:80])
                continue
            seen.add(urn)
            # For reposts, link to the original post rather than the wrapper
            original_urn = item.get("original_urn")
            source_url = urn_to_url(original_urn) if original_urn else urn_to_url(urn)
            posts.append(
                RawPost(
                    platform="linkedin",
                    urn=urn,
                    author=item.get("author"),
                    subtitle=item.get("subtitle"),
                    date_raw=item.get("date"),
                    content=item.get("content", ""),
                    source_url=source_url,
                )
            )
        logger.info("linkedin.playwright_loaded", count=len(posts))
        return posts

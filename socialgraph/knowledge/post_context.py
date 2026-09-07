"""Pack post + article + useful comments into LLM context."""

from __future__ import annotations

from typing import Any

from socialgraph.knowledge.comment_rank import useful_comments


def build_post_context(
    post: Any,
    *,
    max_chars: int = 2800,
    include_comments: bool = True,
    comment_limit: int = 5,
) -> str:
    """Build a multi-source context string for classification, titles, and insights."""
    parts: list[str] = []

    title = (getattr(post, "title", None) or "").strip()
    if title:
        parts.append(f"Existing knowledge title:\n{title[:300]}")

    summary = (getattr(post, "summary", None) or "").strip()
    if summary:
        parts.append(f"Existing evidence summary:\n{summary[:900]}")

    parts.append(f"Original post:\n{(getattr(post, 'content', None) or '')[:1800]}")

    for pel in getattr(post, "post_links", None) or []:
        if getattr(pel, "context", "body") != "body":
            continue
        link = getattr(pel, "external_link", None)
        if link is None:
            continue
        title = getattr(link, "title", None) or getattr(link, "url", "") or ""
        summary = getattr(link, "ai_summary", None) or getattr(link, "description", None) or ""
        excerpt = getattr(link, "body_excerpt", None) or ""
        blob = summary or excerpt[:900]
        if title or blob:
            parts.append(f"Linked article ({title}):\n{blob[:900]}")

    if include_comments:
        for comment in useful_comments(getattr(post, "comments", None), limit=comment_limit):
            author = getattr(comment, "author", None) or "Someone"
            text = (getattr(comment, "text", None) or "").strip()[:320]
            if text:
                parts.append(f"Comment by {author}: {text}")

    packed = "\n\n".join(parts)
    return packed[:max_chars]

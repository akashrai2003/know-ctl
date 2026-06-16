"""Shared utility functions used across multiple modules."""

from __future__ import annotations

import re


def slugify(text: str, max_length: int = 80) -> str:
    """Convert text to a lowercase ASCII slug suitable for filenames and URLs.

    Args:
        text: Input string to slugify.
        max_length: Maximum length of the returned slug.

    Returns:
        Lowercased slug with non-alphanumeric runs replaced by underscores.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower())
    return slug.strip("_")[:max_length]


def urn_tail(urn: str) -> str:
    """Extract the trailing numeric ID from a URN.

    Example::

        >>> urn_tail("urn:li:activity:7458137957485699072")
        '7458137957485699072'

    Args:
        urn: LinkedIn-style URN string.

    Returns:
        The final colon-separated segment.
    """
    return urn.split(":")[-1]


def msg_preview(messages: list[dict], max_chars: int = 300) -> str:
    """Return a short preview of the last user message for log context.

    Args:
        messages: List of chat message dicts with ``role`` and ``content`` keys.
        max_chars: Maximum characters to include in preview.

    Returns:
        Truncated content string of the last user message, or empty string.
    """
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            return content[:max_chars] + ("…" if len(content) > max_chars else "")
    return ""

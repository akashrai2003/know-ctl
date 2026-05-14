from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _yaml_str(s: Any) -> str:
    """Escape a value for safe embedding in a YAML double-quoted scalar.

    Handles backslash, double-quote, all line breaks (\\n, \\r, U+2028, U+2029),
    tab, NUL, and other C0/DEL control characters. Prevents hostile content in
    author names or post text from injecting sibling YAML keys.

    Copied from graphify/export.py (MIT License) — do not simplify.
    """
    if s is None:
        return ""
    out: list[str] = []
    for ch in str(s):
        cp = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\0":
            out.append("\\0")
        elif cp == 0x2028:  # U+2028 LINE SEPARATOR
            out.append("\\L")
        elif cp == 0x2029:  # U+2029 PARAGRAPH SEPARATOR
            out.append("\\P")
        elif cp < 0x20 or cp == 0x7F:
            out.append(f"\\x{cp:02x}")
        else:
            out.append(ch)
    return "".join(out)


def _slug(text: str) -> str:
    """Convert a string to a safe filesystem slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:80]


def _urn_tail(urn: str) -> str:
    """Extract the numeric ID from a URN like urn:li:activity:7458137957485699072."""
    return urn.split(":")[-1]


def _clean_date(date_raw: str | None) -> str:
    """Strip LinkedIn suffix (' •  ' etc.) from date_raw and return a clean display string."""
    if not date_raw:
        return ""
    cleaned = date_raw.split("•")[0].strip()
    return cleaned


_URL_RE = re.compile(r"https?://[^\s\]\[\"'<>]+")


def _extract_urls(text: str) -> list[str]:
    """Extract all HTTP(S) URLs from raw post text. Used before enrich has run."""
    seen: set[str] = set()
    out: list[str] = []
    for url in _URL_RE.findall(text):
        # strip trailing punctuation that's likely not part of the URL
        url = url.rstrip(".,);:")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def render_post_note(
    urn: str,
    platform: str,
    author: str | None,
    subtitle: str | None,
    date_raw: str | None,
    content: str,
    source_url: str | None,
    topic_names: list[str],
    external_links: list[dict],
    comments_notable: bool,
    community: str | None,
    confidence: str,
    created_at: datetime,
    title: str | None = None,
    summary: str | None = None,
) -> str:
    """Render an Obsidian note for a single post."""
    # Use [[slug|DisplayName]] so Obsidian resolves to the actual topic file
    topic_links = "\n".join(
        f'  - "[[{_slug(t)}|{_yaml_str(t)}]]"' for t in topic_names
    )
    ext_links_yaml = ""
    if external_links:
        items = []
        for lnk in external_links:
            title_str = _yaml_str(lnk.get("title") or "")
            url_str = _yaml_str(lnk.get("url") or "")
            summary_str = _yaml_str(lnk.get("description") or "")
            items.append(
                f'  - url: "{url_str}"\n    title: "{title_str}"\n    summary: "{summary_str}"'
            )
        ext_links_yaml = "external_links:\n" + "\n".join(items)
    else:
        ext_links_yaml = "external_links: []"

    tags = ["linkedin"] + [f'"[[{_slug(t)}|{_yaml_str(t)}]]"' for t in topic_names]
    tags_yaml = "\n".join(f"  - {t}" for t in tags)

    frontmatter = f"""\
---
id: "{_yaml_str(urn)}"
platform: "{_yaml_str(platform)}"
author: "{_yaml_str(author)}"
subtitle: "{_yaml_str(subtitle)}"
date_raw: "{_yaml_str(date_raw)}"
topics:
{topic_links}
source_url: "{_yaml_str(source_url)}"
{ext_links_yaml}
comments_notable: {str(comments_notable).lower()}
graph_community: "{_yaml_str(community)}"
confidence: "{_yaml_str(confidence)}"
created_at: "{created_at.date()}"
tags:
{tags_yaml}
---"""

    heading = title.split("\n")[0] if title else f"Post by {author or 'Unknown'}"
    subtitle_line = title.split("\n")[1] if title and "\n" in title else ""

    body = f"\n# {heading}\n"
    if subtitle_line:
        body += f"_{subtitle_line}_\n"
    body += "\n"

    if summary:
        body += f"{summary}\n"
    else:
        body += f"{content[:600].strip()}\n"

    # Links section — show enriched links if available, else extract raw URLs from content
    if external_links:
        body += "\n## Links\n"
        for lnk in external_links:
            url = lnk.get("url", "")
            lnk_title = lnk.get("title") or url
            desc = lnk.get("description", "")
            body += f"\n- [{lnk_title}]({url})"
            if desc:
                body += f"\n  > {desc}"
        body += "\n"
    else:
        raw_urls = _extract_urls(content)
        if raw_urls:
            body += "\n## Links\n"
            for url in raw_urls:
                body += f"\n- {url}"
            body += "\n"

    if source_url:
        body += f"\n[View on LinkedIn]({source_url})\n"

    return frontmatter + body


def render_topic_note(
    name: str,
    description: str,
    subtopic_groups: dict[str, list[dict]],
    related_topics: list[str],
) -> str:
    """Render a topic MOC note.

    ``subtopic_groups`` maps subtopic_name → list of post entry dicts, each with:
    ``urn``, ``author``, ``date_raw``, ``title``, ``content``.
    Pass a single key ``""`` (empty string) if subtopics are not available.
    """
    slug = _slug(name)
    total = sum(len(v) for v in subtopic_groups.values())

    sections: list[str] = []
    for subtopic_name, entries in sorted(subtopic_groups.items()):
        lines: list[str] = []
        for p in entries:
            date_str = _clean_date(p.get("date_raw"))
            date_prefix = f"({date_str}) " if date_str else ""
            post_title = p.get("title") or p.get("content", "")[:80].strip()
            # Flatten two-line title to single line for list display
            post_title = post_title.replace("\n", ". ").strip()
            post_tail = _urn_tail(p["urn"])
            author_str = _yaml_str(p.get("author"))
            lines.append(f"- {date_prefix}[[post_{post_tail}]] — {author_str}: {post_title}")
        block = "\n".join(lines)
        if subtopic_name:
            sections.append(f"### {subtopic_name}\n\n{block}")
        else:
            sections.append(block)

    posts_body = "\n\n".join(sections)
    related = "\n".join(f"- [[{_slug(t)}|{t}]]" for t in related_topics)

    return f"""\
---
type: topic
name: "{_yaml_str(name)}"
post_count: {total}
tags: [topic, {slug}]
---

# {name}

> {total} posts

{description}

## Posts in this topic

{posts_body}

## Related Topics

{related}
"""


def render_index(
    topic_names: list[str],
    total_posts: int,
    generated_at: datetime,
) -> str:
    topic_links = "\n".join(f"- [[{_slug(t)}|{t}]]" for t in sorted(topic_names))
    return f"""\
# Social Graph Index

Generated: {generated_at.strftime("%Y-%m-%d %H:%M")}
Total posts: {total_posts}
Topics: {len(topic_names)}

## Topics

{topic_links}
"""


class VaultWriter:
    """Writes Obsidian vault files from graph/post data."""

    def __init__(self, vault_path: Path) -> None:
        self._vault = vault_path

    def write_post(self, urn: str, content: str) -> Path:
        tail = _urn_tail(urn)
        path = self._vault / "posts" / f"post_{tail}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def write_topic(self, name: str, content: str) -> Path:
        safe = _slug(name)
        path = self._vault / "topics" / f"{safe}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def write_index(self, content: str) -> Path:
        path = self._vault / "_index.md"
        path.write_text(content, encoding="utf-8")
        return path

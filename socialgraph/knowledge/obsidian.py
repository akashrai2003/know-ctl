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


def _escape_wikilinks(text: str) -> str:
    """Escape [[ in user content so Obsidian doesn't parse them as wiki-links."""
    return text.replace("[[", r"\[\[")


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
    comments: list[dict] | None = None,
    topic_subtopic_map: dict[str, str] | None = None,
    all_topic_names: list[str] | None = None,
    comment_links: list[dict] | None = None,
    related_posts: list[str] | None = None,
) -> str:
    """Render an Obsidian note for a single post.

    ``topic_names`` should contain only the PRIMARY topic — it drives the graph
    edge (post → subtopic → topic hierarchy).  Pass a single-element list.
    ``all_topic_names`` is the full set of topics for the post; used only for
    tags (Obsidian filtering) and does NOT create extra graph edges.
    ``topic_subtopic_map`` maps topic_name → subtopic_name for this post.
    ``comment_links`` are ExternalLink dicts sourced from post comments — shown
    in a separate "Comment Links" section with the commenter's context.
    """
    # Build topics: list — point to subtopic when available so the graph edge goes
    # post → subtopic → topic (hierarchy) rather than post → topic directly.
    topic_link_items: list[str] = []
    for t in topic_names:
        sub = (topic_subtopic_map or {}).get(t)
        if sub:
            st_file = f"{_slug(t)}__{_slug(sub)}"
            topic_link_items.append(f'  - "[[{st_file}|{_yaml_str(sub)}]]"')
        else:
            topic_link_items.append(f'  - "[[{_slug(t)}|{_yaml_str(t)}]]"')
    topic_links = "\n".join(topic_link_items)

    ext_links_yaml = ""
    if external_links:
        items = []
        for lnk in external_links:
            title_str = _yaml_str(lnk.get("title") or "")
            url_str = _yaml_str(lnk.get("url") or "")
            summary_str = _yaml_str(lnk.get("ai_summary") or lnk.get("description") or "")
            items.append(
                f'  - url: "{url_str}"\n    title: "{title_str}"\n    summary: "{summary_str}"'
            )
        ext_links_yaml = "external_links:\n" + "\n".join(items)
    else:
        ext_links_yaml = "external_links: []"

    related_posts_yaml = ""
    if related_posts:
        items = []
        for ref in related_posts:
            items.append(f'  - "{ref}"')
        related_posts_yaml = "related_posts:\n" + "\n".join(items)
    else:
        related_posts_yaml = "related_posts: []"

    # Tags: include ALL topics (primary + secondary) as plain slugs so the user
    # can still filter posts by any topic in Obsidian without creating graph edges.
    tag_topics = all_topic_names if all_topic_names is not None else topic_names
    tags = [platform.lower()] + [_slug(t) for t in tag_topics]
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
{related_posts_yaml}
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
        body += f"{_escape_wikilinks(summary)}\n"
    else:
        body += f"{_escape_wikilinks(content.strip())}\n"

    # Links section — show enriched links if available, else extract raw URLs from content
    if external_links:
        body += "\n## Links\n"
        for lnk in external_links:
            url = lnk.get("url", "")
            lnk_title = lnk.get("title") or url
            desc = lnk.get("description", "")
            body += f"\n- [{lnk_title}]({url})"
            if desc:
                body += f"\n  > {_escape_wikilinks(desc)}"
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

    # Comments section — show top notable comments (those with a URL or long text)
    if comments:
        notable = [
            c for c in comments
            if c.get("has_external_url") or len(c.get("text", "")) > 100
        ][:3]
        if notable:
            body += "\n## Comments\n"
            for c in notable:
                cauthor = c.get("author") or "Anonymous"
                ctext = _escape_wikilinks(c.get("text", "").strip()[:400])
                body += f"\n> **{cauthor}**: {ctext}\n"

    # Comment-sourced external links — shown separately so the reader knows
    # these were shared by community members, not by the original author.
    if comment_links:
        body += "\n## Comment Links\n"
        for lnk in comment_links:
            url = lnk.get("url", "")
            lnk_title = lnk.get("title") or url
            ai_summary = lnk.get("ai_summary") or lnk.get("description") or ""
            commenter = lnk.get("commenter") or ""
            comment_text = lnk.get("comment_text") or ""
            body += f"\n- [{lnk_title}]({url})"
            if commenter or comment_text:
                context_parts = []
                if commenter:
                    context_parts.append(f"**{commenter}**")
                if comment_text:
                    context_parts.append(f'"{_escape_wikilinks(comment_text[:200])}"')
                body += f"\n  > Shared by {' — '.join(context_parts)}"
            if ai_summary:
                body += f"\n  > {_escape_wikilinks(ai_summary)}"
        body += "\n"

    return frontmatter + body


def render_subtopic_note(
    topic_slug: str,
    topic_name: str,
    subtopic_name: str,
    entries: list[dict],
) -> str:
    """Render an Obsidian note for a single subtopic.

    Links back to the parent topic and lists all posts belonging to it,
    creating the Topic → Subtopic → Post hierarchy in the graph.
    """
    total = len(entries)
    lines: list[str] = []
    for p in entries:
        date_str = _clean_date(p.get("date_raw"))
        date_prefix = f"({date_str}) " if date_str else ""
        post_title = p.get("title") or p.get("content", "")[:80].strip()
        post_title = post_title.replace("\n", ". ").strip()
        post_tail = _urn_tail(p["urn"])
        author_str = _yaml_str(p.get("author"))
        lines.append(f"- {date_prefix}[[post_{post_tail}]] — {author_str}: {post_title}")
    posts_list = "\n".join(lines)
    _slug(subtopic_name)

    return f"""\
---
type: subtopic
parent_topic: "[[{topic_slug}|{_yaml_str(topic_name)}]]"
post_count: {total}
tags: [subtopic, {topic_slug}]
---

# {subtopic_name}

> Part of [[{topic_slug}|{topic_name}]]

{total} posts

## Posts

{posts_list}
"""


def render_topic_note(
    name: str,
    description: str,
    subtopic_groups: dict[str, list[dict]],
    related_topics: list[str],
    topic_slug: str | None = None,
) -> str:
    """Render a topic MOC note.

    ``subtopic_groups`` maps subtopic_name → list of post entry dicts, each with:
    ``urn``, ``author``, ``date_raw``, ``title``, ``content``.
    Named subtopics are listed as plain text (no wikilinks) so the global graph
    shows only the post→subtopic→topic hierarchy via subtopic back-references —
    not an additional topic→subtopic forward edge.
    The empty-string key ``""`` lists posts that have no subtopic directly.
    """
    slug = topic_slug or _slug(name)
    total = sum(len(v) for v in subtopic_groups.values())

    # Subtopics section — plain text (no wikilinks) to avoid creating topic→subtopic
    # graph edges. The subtopic→topic edge via parent_topic is enough for the hierarchy.
    subtopic_lines: list[str] = []
    direct_entries: list[dict] = []
    for subtopic_name, entries in sorted(subtopic_groups.items()):
        if subtopic_name:
            subtopic_lines.append(
                f"- {subtopic_name} — {len(entries)} posts"
            )
        else:
            direct_entries = entries  # posts with no subtopic

    subtopics_body = "\n".join(subtopic_lines) if subtopic_lines else "_(none)_"

    # Direct posts (no subtopic) listed inline
    direct_lines: list[str] = []
    for p in direct_entries:
        date_str = _clean_date(p.get("date_raw"))
        date_prefix = f"({date_str}) " if date_str else ""
        post_title = p.get("title") or p.get("content", "")[:80].strip()
        post_title = post_title.replace("\n", ". ").strip()
        post_tail = _urn_tail(p["urn"])
        author_str = _yaml_str(p.get("author"))
        direct_lines.append(f"- {date_prefix}[[post_{post_tail}]] — {author_str}: {post_title}")
    direct_body = "\n".join(direct_lines) if direct_lines else ""

    related = "\n".join(f"- [[{_slug(t)}|{t}]]" for t in related_topics)

    direct_section = f"\n## Posts (no subtopic)\n\n{direct_body}" if direct_body else ""

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

## Subtopics

{subtopics_body}{direct_section}

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


def render_author_note(
    name: str,
    slug: str,
    subtitle: str | None,
    platform: str,
    post_count: int,
    topics_with_counts: list[tuple[str, int]],
    posts: list[dict],
) -> str:
    """Render an Obsidian note for an author.

    Lists author profile details, top topics they post about, and a list of their posts.
    """
    topics_lines = []
    for topic_name, count in topics_with_counts:
        t_slug = _slug(topic_name)
        topics_lines.append(f"- [[{t_slug}|{topic_name}]] ({count} posts)")
    topics_body = "\n".join(topics_lines) if topics_lines else "_(none)_"

    post_lines = []
    for p in posts:
        date_str = _clean_date(p.get("date_raw"))
        date_prefix = f"({date_str}) " if date_str else ""
        post_title = p.get("title") or p.get("content", "")[:80].strip()
        post_title = post_title.replace("\n", ". ").strip()
        post_tail = _urn_tail(p["urn"])
        post_lines.append(f"- {date_prefix}[[post_{post_tail}]] — {post_title}")
    posts_body = "\n".join(post_lines) if post_lines else "_(none)_"

    return f"""\
---
type: author
name: "{_yaml_str(name)}"
subtitle: "{_yaml_str(subtitle)}"
platform: "{_yaml_str(platform)}"
post_count: {post_count}
tags: [author, {platform}]
---

# {name}

> {subtitle or ""}

Total posts: {post_count}

## Top Topics

{topics_body}

## Posts

{posts_body}
"""


class VaultWriter:
    """Writes Obsidian vault files from graph/post data.

    Files are organised by platform so future sources (Twitter, Reddit, …)
    live in their own subtrees:

        {vault}/
          linkedin/
            posts/   post_<urn_tail>.md
            topics/  <topic-slug>.md
            authors/ <author-slug>.md
          _index.md
    """

    def __init__(self, vault_path: Path) -> None:
        self._vault = vault_path

    def _platform_dir(self, platform: str) -> Path:
        return self._vault / platform.lower()

    def write_post(self, urn: str, content: str, platform: str = "linkedin") -> Path:
        tail = _urn_tail(urn)
        path = self._platform_dir(platform) / "posts" / f"post_{tail}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_topic(self, name: str, content: str, platform: str = "linkedin") -> Path:
        safe = _slug(name)
        path = self._platform_dir(platform) / "topics" / f"{safe}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def clear_subtopics(self, platform: str = "linkedin") -> int:
        """Delete all existing subtopic files before a fresh write. Returns count deleted."""
        subtopics_dir = self._platform_dir(platform) / "subtopics"
        if not subtopics_dir.exists():
            return 0
        deleted = 0
        for f in subtopics_dir.glob("*.md"):
            f.unlink()
            deleted += 1
        return deleted

    def clear_topics(self, platform: str = "linkedin") -> int:
        """Delete all existing topic files before a fresh write. Returns count deleted."""
        topics_dir = self._platform_dir(platform) / "topics"
        if not topics_dir.exists():
            return 0
        deleted = 0
        for f in topics_dir.glob("*.md"):
            f.unlink()
            deleted += 1
        return deleted

    def write_subtopic(
        self, topic_slug: str, subtopic_slug: str, content: str, platform: str = "linkedin"
    ) -> Path:
        path = (
            self._platform_dir(platform)
            / "subtopics"
            / f"{topic_slug}__{subtopic_slug}.md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_author(self, name: str, content: str, platform: str = "linkedin") -> Path:
        safe = _slug(name)
        path = self._platform_dir(platform) / "authors" / f"{safe}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def clear_authors(self, platform: str = "linkedin") -> int:
        """Delete all existing author files before a fresh write. Returns count deleted."""
        authors_dir = self._platform_dir(platform) / "authors"
        if not authors_dir.exists():
            return 0
        deleted = 0
        for f in authors_dir.glob("*.md"):
            f.unlink()
            deleted += 1
        return deleted

    def write_index(self, content: str) -> Path:
        path = self._vault / "_index.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

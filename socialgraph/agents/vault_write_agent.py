"""Vault write agent: write Obsidian .md files from graph/post data."""
from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.knowledge.obsidian import (
    VaultWriter,
    render_index,
    render_post_note,
    render_topic_note,
)
from socialgraph.storage.models import Comment, Post, PostExternalLink, PostSubtopic, PostTopic, Topic

logger = structlog.get_logger(__name__)


def _primary_topic(post: Post) -> str | None:
    """Return the name of the topic with the highest confidence_score for this post."""
    if not post.post_topics:
        return None
    best = max(post.post_topics, key=lambda pt: pt.confidence_score)
    return best.topic.name


class VaultWriteAgent:
    name = "vault_write"

    async def run(self, ctx: StageContext) -> StageOutput:
        writer = VaultWriter(ctx.settings.obsidian_vault_path)
        result = await ctx.db.scalars(
            select(Post)
            .where(Post.status == "graphed")
            .options(
                selectinload(Post.post_topics).selectinload(PostTopic.topic),
                selectinload(Post.post_links).selectinload(PostExternalLink.external_link),
                selectinload(Post.comments),
                selectinload(Post.post_subtopics),
            )
        )
        posts = list(result.all())

        if not posts:
            return StageOutput(stage=self.name, skipped=1, meta={"reason": "no graphed posts"})

        # topic_subtopic_posts[topic_name][subtopic_name] = [post_entry, ...]
        topic_subtopic_posts: dict[str, dict[str, list[dict]]] = {}
        processed = failed = 0

        for post in posts:
            topic_names = [pt.topic.name for pt in post.post_topics]
            ext_links = [
                {
                    "url": pel.external_link.url,
                    "title": pel.external_link.title,
                    "description": pel.external_link.description,
                }
                for pel in post.post_links
                if pel.external_link.fetch_status == "ok"
            ]
            comments_notable = any(
                c.has_external_url for c in post.comments
            ) if hasattr(post, "comments") else False

            try:
                note_content = render_post_note(
                    urn=post.urn,
                    platform=post.platform,
                    author=post.author,
                    subtitle=post.subtitle,
                    date_raw=post.date_raw,
                    content=post.content,
                    source_url=post.source_url,
                    topic_names=topic_names,
                    external_links=ext_links,
                    comments_notable=comments_notable,
                    community=None,
                    confidence="EXTRACTED",
                    created_at=post.created_at,
                    title=post.title,
                    summary=post.summary,
                )
                writer.write_post(post.urn, note_content)
                post.status = "ok"
                processed += 1
            except Exception as exc:
                logger.error("vault_write.post_failed", urn=post.urn, error=str(exc))
                post.status = "failed"
                failed += 1
                continue

            # Only add post to its PRIMARY topic's MOC bucket (highest confidence_score)
            primary = _primary_topic(post)
            if not primary:
                continue

            # Determine subtopic for this post (scoped to primary topic)
            subtopic_name = ""
            if post.post_subtopics:
                # Find the subtopic row matching the primary topic
                primary_topic_id = next(
                    (pt.topic_id for pt in post.post_topics if pt.topic.name == primary), None
                )
                match = next(
                    (ps for ps in post.post_subtopics if ps.topic_id == primary_topic_id),
                    None,
                )
                if match:
                    subtopic_name = match.subtopic_name

            entry = {
                "urn": post.urn,
                "author": post.author,
                "date_raw": post.date_raw,
                "title": post.title,
                "content": post.content,
            }
            topic_subtopic_posts.setdefault(primary, {}).setdefault(subtopic_name, []).append(entry)

        # Write topic MOC files
        topics_result = await ctx.db.scalars(select(Topic))
        all_topics = {t.name: t for t in topics_result.all()}
        for topic_name, subtopic_groups in topic_subtopic_posts.items():
            t = all_topics.get(topic_name)
            try:
                moc = render_topic_note(
                    name=topic_name,
                    description=t.description or "" if t else "",
                    subtopic_groups=subtopic_groups,
                    related_topics=[],
                )
                writer.write_topic(topic_name, moc)
            except Exception as exc:
                logger.warning("vault_write.topic_failed", topic=topic_name, error=str(exc))

        # Write index
        writer.write_index(
            render_index(
                topic_names=list(topic_subtopic_posts.keys()),
                total_posts=processed,
                generated_at=datetime.utcnow(),
            )
        )

        await ctx.db.commit()
        logger.info("vault_write.complete", processed=processed, failed=failed)
        return StageOutput(stage=self.name, processed=processed, failed=failed)

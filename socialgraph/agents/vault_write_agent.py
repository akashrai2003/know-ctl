"""Vault write agent: write Obsidian .md files from graph/post data."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.agents.base import primary_topic as _primary_topic
from socialgraph.knowledge.obsidian import (
    VaultWriter,
    _slug,
    render_author_note,
    render_index,
    render_post_note,
    render_subtopic_note,
    render_topic_note,
)
from socialgraph.storage.enums import FetchStatus, PostStatus
from socialgraph.storage.models import (
    Author,
    Comment,
    Post,
    PostExternalLink,
    PostTopic,
    Topic,
)

UTC = timezone.utc

logger = structlog.get_logger(__name__)


class VaultWriteAgent:
    name = "vault_write"

    async def run(self, ctx: StageContext) -> StageOutput:
        writer = VaultWriter(ctx.settings.obsidian_vault_path)
        result = await ctx.db.scalars(
            select(Post)
            .where(Post.status.in_(["graphed", "ok"]))
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

        # Load all embeddings if available for similar posts check
        from socialgraph.knowledge.search import build_similarity_map, load_embeddings

        all_embeddings = []
        try:
            all_embeddings = await load_embeddings(ctx.db)
        except Exception as e:
            logger.warning("vault_write.embeddings_load_failed", error=str(e))
        similarity_map = build_similarity_map(all_embeddings, top_k=5, min_score=0.85)
        posts_by_id = {p.id: p for p in posts}

        # Clear/re-populate the authors DB table
        await ctx.db.execute(delete(Author))

        # Group posts by author for database storage and vault generation
        author_posts: dict[str, list[Post]] = {}
        for post in posts:
            if post.author:
                author_posts.setdefault(post.author, []).append(post)

        for author_name, posts_for_author in author_posts.items():
            subtitles = [p.subtitle for p in posts_for_author if p.subtitle]
            subtitle = subtitles[0] if subtitles else None
            platform = posts_for_author[0].platform if posts_for_author else "linkedin"

            author_obj = Author(
                name=author_name,
                slug=_slug(author_name),
                subtitle=subtitle,
                platform=platform,
                post_count=len(posts_for_author),
            )
            ctx.db.add(author_obj)

        # topic_subtopic_posts[topic_name][subtopic_name] = [post_entry, ...]
        topic_subtopic_posts: dict[str, dict[str, list[dict]]] = {}
        processed = failed = 0

        for post in posts:
            all_topic_names = [pt.topic.name for pt in post.post_topics]
            primary = _primary_topic(post)
            graph_topic_names = [primary] if primary else []
            topic_subtopic_map: dict[str, str] = {}
            for ps in post.post_subtopics:
                topic_name_for_id = next(
                    (pt.topic.name for pt in post.post_topics if pt.topic_id == ps.topic_id),
                    None,
                )
                if topic_name_for_id:
                    topic_subtopic_map[topic_name_for_id] = ps.subtopic_name

            ext_links = [
                {
                    "url": pel.external_link.url,
                    "title": pel.external_link.title,
                    "description": pel.external_link.description,
                    "ai_summary": pel.external_link.ai_summary,
                }
                for pel in post.post_links
                if pel.context == "body" and pel.external_link.fetch_status == FetchStatus.OK.value
            ]

            comment_lookup: dict[int, Comment] = {c.id: c for c in (post.comments or [])}
            comment_links_data = []
            for pel in post.post_links:
                if (
                    pel.context != "comment"
                    or pel.external_link.fetch_status != FetchStatus.OK.value
                ):
                    continue
                lnk = pel.external_link
                commenter_comment = comment_lookup.get(pel.comment_id) if pel.comment_id else None
                comment_links_data.append(
                    {
                        "url": lnk.url,
                        "title": lnk.title,
                        "description": lnk.description,
                        "ai_summary": lnk.ai_summary,
                        "commenter": commenter_comment.author if commenter_comment else None,
                        "comment_text": (commenter_comment.text or "")[:200]
                        if commenter_comment
                        else None,
                    }
                )

            comments_notable = (
                any(c.has_external_url for c in post.comments)
                if hasattr(post, "comments")
                else False
            )
            notable_comments = (
                [
                    {"author": c.author, "text": c.text, "has_external_url": c.has_external_url}
                    for c in post.comments
                ]
                if post.comments
                else []
            )

            # Cosine similarity matching
            related_posts = []
            if post.id in similarity_map:
                for other_id, score in similarity_map[post.id]:
                    other_post = posts_by_id.get(other_id)
                    if other_post:
                        tail = other_post.urn.split(":")[-1]
                        other_title = other_post.title or (other_post.content[:50] + "...")
                        other_title = other_title.replace('"', "").replace("\n", " ").strip()
                        related_posts.append(f"[[post_{tail}|{other_title}]]")

            try:
                note_content = render_post_note(
                    urn=post.urn,
                    platform=post.platform,
                    author=post.author,
                    subtitle=post.subtitle,
                    date_raw=post.date_raw,
                    content=post.content,
                    source_url=post.source_url,
                    topic_names=graph_topic_names,
                    all_topic_names=all_topic_names,
                    external_links=ext_links,
                    comments_notable=comments_notable,
                    community=None,
                    confidence="EXTRACTED",
                    created_at=post.created_at,
                    title=post.title,
                    summary=post.summary,
                    comments=notable_comments,
                    topic_subtopic_map=topic_subtopic_map,
                    comment_links=comment_links_data or None,
                    related_posts=related_posts,
                )
                writer.write_post(post.urn, note_content, platform=post.platform)
                post.status = PostStatus.OK.value
                processed += 1
            except Exception as exc:
                logger.error("vault_write.post_failed", urn=post.urn, error=str(exc))
                post.status = PostStatus.FAILED.value
                failed += 1
                continue

            # Add post ONLY to its PRIMARY topic bucket so that subtopic notes
            # only link primary-topic posts — prevents backlink edges from
            # secondary-topic subtopic notes creating extra graph connections.
            entry = {
                "urn": post.urn,
                "author": post.author,
                "date_raw": post.date_raw,
                "title": post.title,
                "content": post.content,
            }
            if primary:
                primary_pt = next((pt for pt in post.post_topics if pt.topic.name == primary), None)
                if primary_pt:
                    sub_for_primary = ""
                    match = next(
                        (ps for ps in post.post_subtopics if ps.topic_id == primary_pt.topic_id),
                        None,
                    )
                    if match:
                        sub_for_primary = match.subtopic_name
                    topic_subtopic_posts.setdefault(primary, {}).setdefault(
                        sub_for_primary, []
                    ).append(entry)

        # Write topic MOC files — grouped by platform
        # Collect the platform for each topic from the posts that reference it
        topic_platform: dict[str, str] = {}
        for post in posts:
            for pt in post.post_topics:
                topic_platform.setdefault(pt.topic.name, post.platform)

        # Clear stale topic, subtopic AND author files from previous runs before writing fresh ones
        for platform_name in set(topic_platform.values()):
            writer.clear_topics(platform=platform_name)
            writer.clear_subtopics(platform=platform_name)
            writer.clear_authors(platform=platform_name)

        # Write author pages
        for author_name, posts_for_author in author_posts.items():
            topic_counts: dict[str, int] = {}
            for p in posts_for_author:
                for pt in p.post_topics:
                    topic_counts[pt.topic.name] = topic_counts.get(pt.topic.name, 0) + 1
            sorted_topics = sorted(topic_counts.items(), key=lambda x: (-x[1], x[0]))

            sorted_posts_for_render = sorted(
                posts_for_author, key=lambda p: p.created_at or datetime.min, reverse=True
            )
            posts_data = [
                {
                    "urn": p.urn,
                    "title": p.title,
                    "date_raw": p.date_raw,
                    "content": p.content,
                }
                for p in sorted_posts_for_render
            ]

            subtitles = [p.subtitle for p in posts_for_author if p.subtitle]
            subtitle = subtitles[0] if subtitles else None
            platform = posts_for_author[0].platform if posts_for_author else "linkedin"

            author_slug = _slug(author_name)
            author_note = render_author_note(
                name=author_name,
                _author_slug=author_slug,
                subtitle=subtitle,
                platform=platform,
                post_count=len(posts_for_author),
                topics_with_counts=sorted_topics[:5],
                posts=posts_data,
            )
            writer.write_author(author_name, author_note, platform=platform)

        topics_result = await ctx.db.scalars(select(Topic))
        all_topics = {t.name: t for t in topics_result.all()}
        subtopic_count = 0

        # Write topic notes for ALL topics in the DB — not just those that have
        # primary-topic posts — to avoid stale files with broken wikilinks.
        for topic_name, t in all_topics.items():
            subtopic_groups = topic_subtopic_posts.get(topic_name, {})
            t_slug = _slug(topic_name)
            platform = topic_platform.get(topic_name, "linkedin")
            try:
                moc = render_topic_note(
                    name=topic_name,
                    description=t.description or "" if t else "",
                    subtopic_groups=subtopic_groups,
                    related_topics=[],
                    topic_slug=t_slug,
                )
                writer.write_topic(topic_name, moc, platform=platform)
            except Exception as exc:
                logger.warning("vault_write.topic_failed", topic=topic_name, error=str(exc))

            # Write individual subtopic notes for topics that do have primary-topic posts
            for subtopic_name, entries in subtopic_groups.items():
                if not subtopic_name:
                    continue  # posts with no subtopic — no separate note needed
                try:
                    st_note = render_subtopic_note(
                        topic_slug=t_slug,
                        topic_name=topic_name,
                        subtopic_name=subtopic_name,
                        entries=entries,
                    )
                    writer.write_subtopic(t_slug, _slug(subtopic_name), st_note, platform=platform)
                    subtopic_count += 1
                except Exception as exc:
                    logger.warning(
                        "vault_write.subtopic_failed",
                        topic=topic_name,
                        subtopic=subtopic_name,
                        error=str(exc),
                    )

        # Write index
        writer.write_index(
            render_index(
                topic_names=list(topic_subtopic_posts.keys()),
                total_posts=processed,
                generated_at=datetime.now(UTC),
            )
        )

        await ctx.db.commit()
        logger.info(
            "vault_write.complete", processed=processed, failed=failed, subtopics=subtopic_count
        )
        return StageOutput(stage=self.name, processed=processed, failed=failed)

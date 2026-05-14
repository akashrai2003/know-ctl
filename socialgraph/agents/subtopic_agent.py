"""Subtopic agent: generate LLM titles and subtopics for posts within each topic.

Pipeline:
  1. For each topic, collect its primary posts (posts where this is the highest-confidence topic).
  2. Bootstrap: first min(5, N) posts → seed the subtopic list for that topic.
  3. Main pass: all remaining posts in batches of 10 with the growing subtopic list.
  4. Groq merge pass: consolidate overlapping subtopics per topic.
  5. Persist Post.title and PostSubtopic rows.
"""
from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.llm.prompts import (
    GENERATE_POST_TITLE_SUBTOPIC_SYSTEM,
    GENERATE_POST_TITLE_SUBTOPIC_USER,
    MERGE_SUBTOPICS_SYSTEM,
    MERGE_SUBTOPICS_USER,
)
from socialgraph.llm.router import LLMRouter
from socialgraph.storage.models import Post, PostSubtopic, PostTopic, Topic
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)

_TITLE_SUBTOPIC_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "PostTitleSubtopic",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "subtopic": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["title", "subtopic", "summary"],
            "additionalProperties": False,
        },
    },
}

_BOOTSTRAP_SIZE = 5
_BATCH_SIZE = 10


def _build_message(post: Post, topic_name: str, existing_subtopics: list[str]) -> list[dict]:
    subtopics_str = (
        "\n".join(f"- {s}" for s in existing_subtopics) if existing_subtopics else "(none yet)"
    )
    return [
        {"role": "system", "content": GENERATE_POST_TITLE_SUBTOPIC_SYSTEM},
        {
            "role": "user",
            "content": GENERATE_POST_TITLE_SUBTOPIC_USER.format(
                topic_name=topic_name,
                existing_subtopics=subtopics_str,
                content=post.content[:800],
            ),
        },
    ]


def _primary_topic(post: Post) -> PostTopic | None:
    """Return the PostTopic with the highest confidence_score for this post."""
    if not post.post_topics:
        return None
    return max(post.post_topics, key=lambda pt: pt.confidence_score)


class SubtopicAgent:
    name = "subtopic"

    def __init__(self, router: LLMRouter) -> None:
        self._router = router

    async def run(self, ctx: StageContext) -> StageOutput:
        client = self._router.batch_client
        groq = self._router.groq_client

        # Load all classified/graphed/ok posts with their topics
        result = await ctx.db.scalars(
            select(Post)
            .where(Post.status.in_(["classified", "graphed", "ok"]))
            .options(
                selectinload(Post.post_topics).selectinload(PostTopic.topic),
            )
        )
        posts = list(result.all())

        if not posts:
            return StageOutput(stage=self.name, skipped=1, meta={"reason": "no posts"})

        repo = Repo(ctx.db)

        # Group posts by primary topic
        topic_groups: dict[str, list[Post]] = {}
        topic_id_map: dict[str, int] = {}

        for post in posts:
            pt = _primary_topic(post)
            if pt:
                topic_name = pt.topic.name
                topic_groups.setdefault(topic_name, []).append(post)
                topic_id_map[topic_name] = pt.topic_id

        total_processed = total_failed = 0

        for topic_name, topic_posts in topic_groups.items():
            topic_id = topic_id_map[topic_name]
            existing_subtopics: list[str] = []

            logger.info(
                "subtopic.processing_topic",
                topic=topic_name,
                post_count=len(topic_posts),
            )

            # ── Bootstrap: first min(5, N) posts ────────────────────────
            bootstrap = topic_posts[: _BOOTSTRAP_SIZE]
            messages_list = [_build_message(p, topic_name, []) for p in bootstrap]
            results = await client.batch_chat(messages_list, response_format=_TITLE_SUBTOPIC_RESPONSE_FORMAT)

            for post, res in zip(bootstrap, results, strict=False):
                if not res:
                    total_failed += 1
                    continue
                await _apply_result(post, res, topic_id, repo, existing_subtopics)
                total_processed += 1

            # ── Main pass: remaining posts in batches of 10 ─────────────
            remaining = topic_posts[_BOOTSTRAP_SIZE:]
            for i in range(0, len(remaining), _BATCH_SIZE):
                batch = remaining[i : i + _BATCH_SIZE]
                messages_list = [_build_message(p, topic_name, existing_subtopics) for p in batch]
                results = await client.batch_chat(
                    messages_list, response_format=_TITLE_SUBTOPIC_RESPONSE_FORMAT
                )
                for post, res in zip(batch, results, strict=False):
                    if not res:
                        total_failed += 1
                        continue
                    await _apply_result(post, res, topic_id, repo, existing_subtopics)
                    total_processed += 1

            # ── Groq merge pass: consolidate overlapping subtopics ───────
            if len(existing_subtopics) >= 4:
                await _merge_subtopics(existing_subtopics, topic_name, topic_id, repo, groq)

        await ctx.db.commit()
        logger.info("subtopic.complete", processed=total_processed, failed=total_failed)
        return StageOutput(stage=self.name, processed=total_processed, failed=total_failed)


async def _apply_result(
    post: Post,
    res: dict,
    topic_id: int,
    repo: Repo,
    existing_subtopics: list[str],
) -> None:
    title = (res.get("title") or "").strip()
    subtopic = (res.get("subtopic") or "").strip()
    summary = (res.get("summary") or "").strip()

    if title:
        post.title = title
    if summary:
        post.summary = summary
    if subtopic:
        # Normalize: check if it's close to an existing subtopic (exact match ignoring case)
        canonical = next(
            (s for s in existing_subtopics if s.lower() == subtopic.lower()), subtopic
        )
        if canonical not in existing_subtopics:
            existing_subtopics.append(canonical)
        await repo.upsert_post_subtopic(post.id, topic_id, canonical)
    logger.debug(
        "subtopic.post_done",
        post_id=post.id,
        title_preview=title[:60] if title else None,
        subtopic=subtopic,
    )


async def _merge_subtopics(
    existing_subtopics: list[str],
    topic_name: str,
    topic_id: int,
    repo: Repo,
    groq_client: object,
) -> None:
    subtopic_list = "\n".join(f"- {s}" for s in existing_subtopics)
    result = groq_client.complete(  # type: ignore[union-attr]
        [
            {"role": "system", "content": MERGE_SUBTOPICS_SYSTEM},
            {
                "role": "user",
                "content": MERGE_SUBTOPICS_USER.format(
                    topic_name=topic_name,
                    count=len(existing_subtopics),
                    subtopic_list=subtopic_list,
                ),
            },
        ],
        response_format={"type": "json_object"},
    )
    if not result or not result.get("merges"):
        return

    for merge in result["merges"]:
        keep = merge.get("keep", "").strip()
        remove = merge.get("remove", [])
        if not keep or not remove:
            continue
        for old_name in remove:
            count = await repo.rename_subtopic_in_topic(old_name.strip(), keep, topic_id)
            if count:
                logger.info(
                    "subtopic.merged",
                    topic=topic_name,
                    old=old_name,
                    new=keep,
                    rows=count,
                )

"""Subtopic agent: generate LLM titles and subtopics for posts within each topic.

Pipeline:
  1. For each topic, collect posts where it is the primary/highest-confidence topic.
  2. Bootstrap: first min(5, N) posts → seed the subtopic list for that topic.
  3. Main pass: all remaining posts in batches of 10 with the growing subtopic list.
  4. Local-model merge pass: consolidate overlapping subtopics per topic.
  5. Persist Post.title and PostSubtopic rows.
"""

from __future__ import annotations

import re
from typing import Any, TypeGuard

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.agents.base import primary_topic as _primary_topic
from socialgraph.knowledge.post_context import build_post_context
from socialgraph.llm.prompts import (
    GENERATE_POST_TITLE_SUBTOPIC_SYSTEM,
    GENERATE_POST_TITLE_SUBTOPIC_USER,
    MERGE_SUBTOPICS_SYSTEM,
    MERGE_SUBTOPICS_USER,
)
from socialgraph.llm.router import LLMRouter
from socialgraph.storage.models import Post, PostExternalLink, PostSubtopic, PostTopic
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
_MAX_TOKENS = 700
_RETRY_MAX_TOKENS = 1000

_MERGE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "SubtopicMerges",
        "schema": {
            "type": "object",
            "properties": {
                "merges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "keep": {"type": "string"},
                            "remove": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["keep", "remove"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["merges"],
            "additionalProperties": False,
        },
    },
}


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
                content=build_post_context(post, max_chars=2200),
            ),
        },
    ]


class SubtopicAgent:
    name = "subtopic"

    def __init__(
        self,
        router: LLMRouter,
        *,
        force: bool = False,
        topic_names: list[str] | None = None,
    ) -> None:
        self._router = router
        self._force = force
        self._topic_names = set(topic_names or [])

    async def run(self, ctx: StageContext) -> StageOutput:
        client = self._router.batch_client

        # Load all classified/graphed/ok posts with their topics
        result = await ctx.db.scalars(
            select(Post)
            .where(Post.status.in_(["classified", "graphed", "ok"]))
            .options(
                selectinload(Post.post_topics).selectinload(PostTopic.topic),
                selectinload(Post.post_subtopics),
                selectinload(Post.comments),
                selectinload(Post.post_links).selectinload(PostExternalLink.external_link),
            )
        )
        posts = list(result.all())

        if not posts:
            return StageOutput(stage=self.name, skipped=1, meta={"reason": "no posts"})

        repo = Repo(ctx.db)

        # A post belongs to one navigational hierarchy. Secondary topics remain tags,
        # but do not create competing subtopic assignments.
        topic_groups: dict[str, list[Post]] = {}
        topic_id_map: dict[str, int] = {}

        for post in posts:
            topic_name = _primary_topic(post)
            if not topic_name:
                continue
            if self._topic_names and topic_name not in self._topic_names:
                continue
            primary_pt = next(pt for pt in post.post_topics if pt.topic.name == topic_name)
            topic_groups.setdefault(topic_name, []).append(post)
            topic_id_map[topic_name] = primary_pt.topic_id

        total_processed = total_failed = 0

        for topic_name, topic_posts in topic_groups.items():
            topic_id = topic_id_map[topic_name]

            # Seed existing_subtopics from DB so incremental runs stay consistent
            existing_subtopics_result = await ctx.db.scalars(
                select(PostSubtopic.subtopic_name)
                .where(PostSubtopic.topic_id == topic_id)
                .distinct()
            )
            existing_subtopics = [] if self._force else list(existing_subtopics_result.all())

            # Force mode regenerates titles and replaces the old navigational subtopic.
            posts_needing_subtopic = (
                topic_posts
                if self._force
                else [
                    p
                    for p in topic_posts
                    if not any(ps.topic_id == topic_id for ps in p.post_subtopics)
                ]
            )
            if not posts_needing_subtopic:
                logger.debug(
                    "subtopic.topic_already_complete",
                    topic=topic_name,
                    existing_count=len(existing_subtopics),
                )
                continue

            logger.info(
                "subtopic.processing_topic",
                topic=topic_name,
                total_posts=len(topic_posts),
                new_posts=len(posts_needing_subtopic),
                existing_subtopics=len(existing_subtopics),
            )
            topic_posts = posts_needing_subtopic

            # ── Bootstrap: first min(5, N) posts ────────────────────────
            bootstrap = topic_posts[:_BOOTSTRAP_SIZE]
            results = await _generate_batch(
                client,
                bootstrap,
                topic_name,
                [],
            )

            for post, res in zip(bootstrap, results, strict=False):
                if not _valid_result(res):
                    total_failed += 1
                    continue
                await _apply_result(
                    post,
                    res,
                    topic_id,
                    repo,
                    existing_subtopics,
                    replace_existing=self._force,
                )
                total_processed += 1
            await ctx.db.commit()

            # ── Main pass: remaining posts in batches of 10 ─────────────
            remaining = topic_posts[_BOOTSTRAP_SIZE:]
            for i in range(0, len(remaining), _BATCH_SIZE):
                batch = remaining[i : i + _BATCH_SIZE]
                results = await _generate_batch(
                    client,
                    batch,
                    topic_name,
                    existing_subtopics,
                )
                for post, res in zip(batch, results, strict=False):
                    if not _valid_result(res):
                        total_failed += 1
                        continue
                    await _apply_result(
                        post,
                        res,
                        topic_id,
                        repo,
                        existing_subtopics,
                        replace_existing=self._force,
                    )
                    total_processed += 1
                await ctx.db.commit()
                logger.info(
                    "subtopic.progress",
                    topic=topic_name,
                    completed=min(i + len(batch) + len(bootstrap), len(topic_posts)),
                    total=len(topic_posts),
                    processed=total_processed,
                    failed=total_failed,
                )

            # ── Local merge pass: consolidate overlapping subtopics ──────
            if len(existing_subtopics) >= 4:
                await _merge_subtopics(existing_subtopics, topic_name, topic_id, repo, client)
                await ctx.db.commit()

        await ctx.db.commit()
        logger.info("subtopic.complete", processed=total_processed, failed=total_failed)
        return StageOutput(stage=self.name, processed=total_processed, failed=total_failed)


async def _apply_result(
    post: Post,
    res: dict,
    topic_id: int,
    repo: Repo,
    existing_subtopics: list[str],
    *,
    replace_existing: bool = False,
) -> None:
    title = (res.get("title") or "").strip()
    subtopic = (res.get("subtopic") or "").strip()
    summary = (res.get("summary") or "").strip()

    if title:
        post.title = title
    if summary:
        post.summary = summary
    if subtopic:
        if replace_existing:
            await repo.clear_post_subtopics(post.id)
        # Normalize: check if it's close to an existing subtopic (exact match ignoring case)
        canonical = next((s for s in existing_subtopics if s.lower() == subtopic.lower()), subtopic)
        if canonical not in existing_subtopics:
            existing_subtopics.append(canonical)
        await repo.upsert_post_subtopic(post.id, topic_id, canonical)
    logger.debug(
        "subtopic.post_done",
        post_id=post.id,
        title_preview=title[:60] if title else None,
        subtopic=subtopic,
    )


def _valid_result(result: object) -> TypeGuard[dict[str, Any]]:
    return isinstance(result, dict) and bool(str(result.get("subtopic") or "").strip())


async def _generate_batch(
    client: Any,
    posts: list[Post],
    topic_name: str,
    existing_subtopics: list[str],
) -> list[object | None]:
    """Generate a batch and retry only malformed/missing outputs deterministically."""
    if not posts:
        return []
    messages = [_build_message(post, topic_name, existing_subtopics) for post in posts]
    results = await client.batch_chat(
        messages,
        response_format=_TITLE_SUBTOPIC_RESPONSE_FORMAT,
        temperature=0.1,
        max_tokens=_MAX_TOKENS,
    )
    normalized = list(results)
    if len(normalized) < len(posts):
        normalized.extend([None] * (len(posts) - len(normalized)))

    retry_indices = [index for index, result in enumerate(normalized) if not _valid_result(result)]
    if retry_indices:
        retry_results = await client.batch_chat(
            [messages[index] for index in retry_indices],
            response_format=_TITLE_SUBTOPIC_RESPONSE_FORMAT,
            temperature=0.0,
            max_tokens=_RETRY_MAX_TOKENS,
        )
        for retry_offset, original_index in enumerate(retry_indices):
            if retry_offset < len(retry_results):
                normalized[original_index] = retry_results[retry_offset]
    return normalized


async def _merge_subtopics(
    existing_subtopics: list[str],
    topic_name: str,
    topic_id: int,
    repo: Repo,
    client: Any,
) -> None:
    subtopic_list = "\n".join(f"- {s}" for s in existing_subtopics)
    try:
        results = await client.batch_chat(
            [
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
                ]
            ],
            response_format=_MERGE_RESPONSE_FORMAT,
            temperature=0.0,
            max_tokens=800,
        )
        result = results[0] if results else None
    except Exception as exc:
        logger.warning("subtopic.merge_failed", topic=topic_name, error=str(exc))
        return
    if not result or not result.get("merges"):
        return

    known_names = {_normalized_subtopic(name) for name in existing_subtopics}
    for merge in result["merges"]:
        keep = merge.get("keep", "").strip()
        remove = merge.get("remove", [])
        if not keep or not remove:
            continue
        for old_name in remove:
            old_name = old_name.strip()
            if not _safe_subtopic_merge(keep, old_name, known_names):
                logger.info(
                    "subtopic.merge_rejected",
                    topic=topic_name,
                    old=old_name,
                    proposed=keep,
                )
                continue
            count = await repo.rename_subtopic_in_topic(old_name, keep, topic_id)
            if count:
                logger.info(
                    "subtopic.merged",
                    topic=topic_name,
                    old=old_name,
                    new=keep,
                    rows=count,
                )


def _normalized_subtopic(name: str) -> tuple[str, ...]:
    words = re.findall(r"[a-z0-9]+", name.casefold())
    normalized = []
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        normalized.append(word)
    return tuple(normalized)


def _safe_subtopic_merge(
    keep: str,
    remove: str,
    known_names: set[tuple[str, ...]],
) -> bool:
    """Accept only near-duplicate labels; semantic reinterpretation is too risky."""
    keep_words = _normalized_subtopic(keep)
    remove_words = _normalized_subtopic(remove)
    if not keep_words or not remove_words or keep_words not in known_names:
        return False
    if keep_words == remove_words:
        return True
    keep_set = set(keep_words)
    remove_set = set(remove_words)
    smaller = min(len(keep_set), len(remove_set))
    if smaller < 2:
        return False
    if keep_set <= remove_set or remove_set <= keep_set:
        return True
    return len(keep_set & remove_set) / len(keep_set | remove_set) >= 0.75

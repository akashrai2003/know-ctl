"""Classify agent: assign posts to taxonomy topics using vLLM batch."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.knowledge.post_context import build_post_context
from socialgraph.knowledge.taxonomy import Taxonomy
from socialgraph.llm.prompts import CLASSIFY_POST_TOPICS_SYSTEM, CLASSIFY_POST_TOPICS_USER
from socialgraph.llm.router import LLMRouter
from socialgraph.storage.enums import PostStatus
from socialgraph.storage.models import Post, PostExternalLink
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)

_MAX_TOKENS = 300
_RETRY_MAX_TOKENS = 500

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "TopicClassification",
        "schema": {
            "type": "object",
            "properties": {
                "primary_topic": {"type": "string"},
                "secondary_topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 2,
                },
                "confidence": {"type": "number"},
            },
            "required": ["primary_topic", "secondary_topics", "confidence"],
            "additionalProperties": False,
        },
    },
}


class ClassifyAgent:
    name = "classify"
    CHECKPOINT_VERSION = 2

    def __init__(
        self,
        router: LLMRouter,
        taxonomy: Taxonomy,
        *,
        force: bool = False,
        urns: list[str] | None = None,
        fallback_to_groq: bool = True,
    ) -> None:
        self._router = router
        self._taxonomy = taxonomy
        self._force = force
        self._urns = set(urns or [])
        self._fallback_to_groq = fallback_to_groq

    async def run(self, ctx: StageContext) -> StageOutput:

        _load = (
            selectinload(Post.comments),
            selectinload(Post.post_links).selectinload(PostExternalLink.external_link),
        )
        if self._force:
            query = select(Post).where(
                Post.status.in_(["ingested", "enriched", "classified", "graphed", "ok"])
            )
            if self._urns:
                query = query.where(Post.urn.in_(self._urns))
            result = await ctx.db.scalars(query.options(*_load))
            posts = list(result.all())
        else:
            result = await ctx.db.scalars(
                select(Post).where(Post.status.in_(["enriched", "ingested"])).options(*_load)
            )
            posts = list(result.all())

            unclassified_result = await ctx.db.scalars(
                select(Post)
                .where(Post.status.in_(["ok", "graphed"]))
                .where(~Post.post_topics.any())
                .options(*_load)
            )
            posts.extend(unclassified_result.all())

            if self._urns:
                posts = [post for post in posts if post.urn in self._urns]

        if not posts:
            return StageOutput(stage=self.name, skipped=1, meta={"reason": "no classifiable posts"})

        repo = Repo(ctx.db)
        batch_size = ctx.settings.batch_size
        topics_prompt = self._taxonomy.as_prompt_list()
        client = self._router.batch_client
        processed = failed = 0

        for i in range(0, len(posts), batch_size):
            batch = posts[i : i + batch_size]
            messages_list = [
                [
                    {"role": "system", "content": CLASSIFY_POST_TOPICS_SYSTEM},
                    {
                        "role": "user",
                        "content": CLASSIFY_POST_TOPICS_USER.format(
                            topics=topics_prompt,
                            content=build_post_context(p, max_chars=4200),
                        ),
                    },
                ]
                for p in batch
            ]
            results = await _generate_classifications(client, messages_list)
            for offset, post in enumerate(batch):
                raw_result = results[offset] if offset < len(results) else None
                res = raw_result if isinstance(raw_result, dict) else None
                try:
                    applied = await _apply_classification(
                        post,
                        res,
                        repo,
                        self._taxonomy,
                        self._router,
                        replace_existing=self._force,
                        fallback_to_groq=self._fallback_to_groq,
                    )
                    if not applied:
                        failed += 1
                        logger.warning("classify.empty", urn=post.urn)
                        continue
                    # Reset previously-completed posts back to classified so graph_build re-runs
                    post.status = PostStatus.CLASSIFIED.value
                    processed += 1
                except Exception as exc:
                    logger.error("classify.post_failed", urn=post.urn, error=str(exc))
                    if not self._force:
                        post.status = PostStatus.FAILED.value
                    failed += 1

            await ctx.db.commit()
            logger.info(
                "classify.progress",
                completed=min(i + len(batch), len(posts)),
                total=len(posts),
                processed=processed,
                failed=failed,
            )

        logger.info("classify.complete", processed=processed, failed=failed)
        return StageOutput(stage=self.name, processed=processed, failed=failed)


async def _apply_classification(
    post: Post,
    result: dict | None,
    repo: Repo,
    taxonomy: Taxonomy,
    router: LLMRouter,
    *,
    replace_existing: bool = False,
    fallback_to_groq: bool = True,
) -> bool:
    if not result or not (result.get("primary_topic") or result.get("topics")):
        # Escalate to Groq if small model produced nothing
        groq = router.groq_client if fallback_to_groq else None
        if groq is not None:
            prompt = (
                "Choose one primary topic and up to two secondary topics for this post:\n"
                f"{build_post_context(post, max_chars=1200)}\n"
                'Respond as JSON {"primary_topic": "", "secondary_topics": [], '
                '"confidence": 0.0}'
            )
            res = groq.complete(
                [{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            if isinstance(res, dict):
                result = res
            elif isinstance(res, str):
                try:
                    import json

                    result = json.loads(res)
                except Exception:
                    return False
            else:
                return False
        else:
            return False

    raw_score = max(0.0, min(1.0, float(result.get("confidence", 0.75))))
    legacy_topics = result.get("topics") or []
    primary_raw = result.get("primary_topic") or (legacy_topics[0] if legacy_topics else "")
    secondary_raw = result.get("secondary_topics") or legacy_topics[1:]

    canonical_primary = taxonomy.resolve(str(primary_raw))
    if not canonical_primary:
        return False

    canonical_topics = [canonical_primary]
    for raw_name in secondary_raw[:2]:
        canonical = taxonomy.resolve(str(raw_name))
        if canonical and canonical not in canonical_topics:
            canonical_topics.append(canonical)

    if replace_existing:
        await repo.clear_post_taxonomy(post.id)

    for rank, canonical in enumerate(canonical_topics):
        topic, _ = await repo.get_or_create_topic(canonical)
        ranked_score = max(0.0, raw_score - (rank * 0.08))
        confidence_tag = "EXTRACTED" if ranked_score >= 0.8 else "INFERRED"
        await repo.upsert_post_topic(post.id, topic.id, ranked_score, confidence_tag)
    return True


def _valid_classification(result: object) -> bool:
    return isinstance(result, dict) and bool(result.get("primary_topic") or result.get("topics"))


async def _generate_classifications(
    client: Any,
    messages_list: list[list[dict]],
) -> list[object | None]:
    """Generate classifications with an isolated retry for malformed responses."""
    try:
        results = await client.batch_chat(
            messages_list,
            response_format=RESPONSE_FORMAT,
            temperature=0.0,
            max_tokens=_MAX_TOKENS,
        )
    except Exception as exc:
        logger.error("classify.batch_failed", error=str(exc), batch_size=len(messages_list))
        results = []

    normalized = list(results)
    if len(normalized) < len(messages_list):
        normalized.extend([None] * (len(messages_list) - len(normalized)))

    retry_indices = [
        index for index, result in enumerate(normalized) if not _valid_classification(result)
    ]
    if retry_indices:
        try:
            retry_results = await client.batch_chat(
                [messages_list[index] for index in retry_indices],
                response_format=RESPONSE_FORMAT,
                temperature=0.0,
                max_tokens=_RETRY_MAX_TOKENS,
            )
        except Exception as exc:
            logger.error(
                "classify.retry_batch_failed", error=str(exc), batch_size=len(retry_indices)
            )
            retry_results = []
        for retry_offset, original_index in enumerate(retry_indices):
            if retry_offset < len(retry_results):
                normalized[original_index] = retry_results[retry_offset]
    return normalized

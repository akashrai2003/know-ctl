"""Classify agent: assign posts to taxonomy topics using vLLM batch."""

from __future__ import annotations

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

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "TopicClassification",
        "schema": {
            "type": "object",
            "properties": {
                "topics": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
            },
            "required": ["topics", "confidence"],
            "additionalProperties": False,
        },
    },
}


class ClassifyAgent:
    name = "classify"
    CHECKPOINT_VERSION = 1

    def __init__(self, router: LLMRouter, taxonomy: Taxonomy) -> None:
        self._router = router
        self._taxonomy = taxonomy

    async def run(self, ctx: StageContext) -> StageOutput:

        _load = (
            selectinload(Post.comments),
            selectinload(Post.post_links).selectinload(PostExternalLink.external_link),
        )
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
        unclassified_posts = list(unclassified_result.all())
        # Track which ones were previously done so we can reset their status
        needs_regraph: set[int] = {p.id for p in unclassified_posts}
        posts = posts + unclassified_posts

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
                            content=build_post_context(p, max_chars=2200),
                        ),
                    },
                ]
                for p in batch
            ]
            results = await client.batch_chat(messages_list, response_format=RESPONSE_FORMAT)
            for post, res in zip(batch, results, strict=False):
                try:
                    await _apply_classification(post, res, repo, self._taxonomy, self._router)
                    # Reset previously-completed posts back to classified so graph_build re-runs
                    post.status = PostStatus.CLASSIFIED.value
                    processed += 1
                except Exception as exc:
                    logger.error("classify.post_failed", urn=post.urn, error=str(exc))
                    if post.id not in needs_regraph:
                        post.status = PostStatus.FAILED.value
                    failed += 1

        await ctx.db.commit()
        logger.info("classify.complete", processed=processed, failed=failed)
        return StageOutput(stage=self.name, processed=processed, failed=failed)


async def _apply_classification(
    post: Post, result: dict | None, repo: Repo, taxonomy: Taxonomy, router: LLMRouter
) -> None:
    if not result or not result.get("topics"):
        # Escalate to Groq if small model produced nothing
        groq = router.groq_client
        if groq is not None:
            prompt = (
                "List 1-3 topics for this post using the full context:\n"
                f"{build_post_context(post, max_chars=1200)}\n"
                'Respond as JSON {"topics": [], "confidence": 0.0}'
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
                    return
            else:
                return
        else:
            return

    raw_score: float = float(result.get("confidence", 0.75))
    topics: list[str] = result.get("topics", [])

    for raw_name in topics:
        canonical = taxonomy.resolve(raw_name)
        if not canonical:
            # Skip unrecognised topics — don't pollute the taxonomy
            logger.debug("classify.unknown_topic", raw=raw_name)
            continue
        topic, _ = await repo.get_or_create_topic(canonical)
        confidence_tag = "EXTRACTED" if raw_score >= 0.8 else "INFERRED"
        await repo.upsert_post_topic(post.id, topic.id, raw_score, confidence_tag)

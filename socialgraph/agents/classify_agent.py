"""Classify agent: assign posts to taxonomy topics using vLLM batch."""
from __future__ import annotations

import structlog
from sqlalchemy import select

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.knowledge.taxonomy import Taxonomy
from socialgraph.llm.prompts import CLASSIFY_POST_TOPICS_SYSTEM, CLASSIFY_POST_TOPICS_USER
from socialgraph.llm.router import LLMRouter
from socialgraph.storage.models import Post
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

        result = await ctx.db.scalars(
            select(Post).where(Post.status.in_(["enriched", "ingested"]))
        )
        posts = list(result.all())

        # Also reclassify posts that already completed the pipeline but have no topics
        unclassified_result = await ctx.db.scalars(
            select(Post)
            .where(Post.status.in_(["ok", "graphed"]))
            .where(~Post.post_topics.any())
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
                            content=p.content[:800],
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
                    post.status = "classified"
                    processed += 1
                except Exception as exc:
                    logger.error("classify.post_failed", urn=post.urn, error=str(exc))
                    if post.id not in needs_regraph:
                        post.status = "failed"
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
        prompt = f"List 1-3 topics for this post:\n{post.content[:600]}\nRespond as JSON {{\"topics\": [], \"confidence\": 0.0}}"
        result = groq.complete(
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        if not result:
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

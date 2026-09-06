"""Rank comments with deterministic filters plus local-model review. Idempotent."""

from __future__ import annotations

import structlog
from sqlalchemy import select, update

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.knowledge.comment_rank import needs_llm_review, rank_comment
from socialgraph.llm.prompts import RANK_COMMENT_SYSTEM, RANK_COMMENT_USER
from socialgraph.llm.router import LLMRouter
from socialgraph.storage.enums import CommentKind
from socialgraph.storage.models import Comment, Post

logger = structlog.get_logger(__name__)

_RANK_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "CommentUsefulness",
        "schema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["insight", "question", "resource", "noise"],
                },
                "usefulness_score": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["kind", "usefulness_score"],
            "additionalProperties": False,
        },
    },
}
_VALID_KINDS = {kind.value for kind in CommentKind}


class CommentRankAgent:
    name = "rank_comments"

    def __init__(self, router: LLMRouter | None = None, urns: list[str] | None = None) -> None:
        self._router = router
        self._urns = urns

    async def run(self, ctx: StageContext) -> StageOutput:
        query = select(Comment).where(Comment.kind.is_(None))
        if self._urns:
            query = query.join(Post, Post.id == Comment.post_id).where(Post.urn.in_(self._urns))
        result = await ctx.db.scalars(query)
        comments = list(result.all())
        if not comments:
            return StageOutput(
                stage=self.name, skipped=1, meta={"reason": "all comments already ranked"}
            )

        useful = noise = llm_reviewed = 0
        affected_post_ids: set[int] = set()
        review_candidates: list[tuple[Comment, str, float]] = []
        for comment in comments:
            kind, score = rank_comment(comment.text or "", comment.has_external_url)
            affected_post_ids.add(comment.post_id)
            if self._router and needs_llm_review(comment.text or "", kind, score):
                # Leave ambiguous rows unranked until their LLM batch finishes.
                # If the process is interrupted, a rerun can pick them up.
                review_candidates.append((comment, kind, score))
            else:
                comment.kind = kind
                comment.usefulness_score = score

        if review_candidates:
            post_rows = await ctx.db.execute(
                select(Post.id, Post.content).where(
                    Post.id.in_({comment.post_id for comment, _, _ in review_candidates})
                )
            )
            post_content = {post_id: content or "" for post_id, content in post_rows}
        if affected_post_ids:
            await ctx.db.execute(
                update(Post)
                .where(Post.id.in_(affected_post_ids))
                .values(
                    insight_json=None,
                    insight_source_hash=None,
                    insight_generated_at=None,
                )
            )
        # Checkpoint deterministic decisions and briefing invalidation before
        # potentially long-running model review.
        await ctx.db.commit()

        if review_candidates:
            batch_size = max(1, ctx.settings.batch_size)
            client = self._router.batch_client if self._router else None
            total_batches = (len(review_candidates) + batch_size - 1) // batch_size
            for batch_number, start in enumerate(
                range(0, len(review_candidates), batch_size), start=1
            ):
                batch = review_candidates[start : start + batch_size]
                messages = [
                    [
                        {"role": "system", "content": RANK_COMMENT_SYSTEM},
                        {
                            "role": "user",
                            "content": RANK_COMMENT_USER.format(
                                post=post_content.get(comment.post_id, "")[:1200],
                                comment=(comment.text or "")[:1000],
                            ),
                        },
                    ]
                    for comment, _, _ in batch
                ]
                try:
                    results = await client.batch_chat(  # type: ignore[union-attr]
                        messages,
                        response_format=_RANK_RESPONSE_FORMAT,
                        temperature=0.0,
                        max_tokens=100,
                    )
                    for index, (comment, heuristic_kind, heuristic_score) in enumerate(batch):
                        llm_result = results[index] if index < len(results) else None
                        if not isinstance(llm_result, dict):
                            comment.kind = heuristic_kind
                            comment.usefulness_score = heuristic_score
                            continue
                        kind = str(llm_result.get("kind") or "")
                        if kind not in _VALID_KINDS:
                            comment.kind = heuristic_kind
                            comment.usefulness_score = heuristic_score
                            continue
                        try:
                            score = min(
                                1.0,
                                max(0.0, float(llm_result.get("usefulness_score", 0))),
                            )
                        except (TypeError, ValueError):
                            comment.kind = heuristic_kind
                            comment.usefulness_score = heuristic_score
                            continue
                        comment.kind = kind
                        comment.usefulness_score = round(score * 10, 2)
                        llm_reviewed += 1
                except Exception as exc:
                    logger.warning("rank_comments.llm_batch_failed", start=start, error=str(exc))
                    for comment, heuristic_kind, heuristic_score in batch:
                        comment.kind = heuristic_kind
                        comment.usefulness_score = heuristic_score
                await ctx.db.commit()
                logger.info(
                    "rank_comments.progress",
                    batch=batch_number,
                    total_batches=total_batches,
                    completed=min(start + len(batch), len(review_candidates)),
                    review_total=len(review_candidates),
                )

        for comment in comments:
            if comment.kind == CommentKind.NOISE.value:
                noise += 1
            else:
                useful += 1

        await ctx.db.commit()
        logger.info("rank_comments.complete", total=len(comments), useful=useful, noise=noise)
        return StageOutput(
            stage=self.name,
            processed=len(comments),
            meta={"useful": useful, "noise": noise, "llm_reviewed": llm_reviewed},
        )

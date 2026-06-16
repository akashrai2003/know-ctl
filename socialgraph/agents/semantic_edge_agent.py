"""Semantic edge agent: create GraphEdge rows for post pairs with high embedding similarity."""
from __future__ import annotations

import structlog
from sqlalchemy import select

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.knowledge.search import find_similar, load_embeddings
from socialgraph.storage.models import GraphNode, Post
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)

SIMILARITY_THRESHOLD = 0.85
TOP_K_PER_POST = 5


class SemanticEdgeAgent:
    name = "semantic_edges"

    def __init__(self, threshold: float = SIMILARITY_THRESHOLD) -> None:
        self._threshold = threshold

    async def run(self, ctx: StageContext) -> StageOutput:
        # Load all embeddings
        all_embeddings = await load_embeddings(ctx.db)
        if len(all_embeddings) < 2:
            return StageOutput(
                stage=self.name,
                skipped=1,
                meta={"reason": "not enough embeddings; run sg embed first"},
            )

        # Map post_id → GraphNode
        node_result = await ctx.db.scalars(
            select(GraphNode).where(GraphNode.node_type == "post")
        )
        nodes = {n.node_id: n for n in node_result.all()}

        # Build post_id → node_db_id map
        post_result = await ctx.db.scalars(select(Post))
        posts = {p.id: p for p in post_result.all()}

        from socialgraph.knowledge.obsidian import _urn_tail

        def _node_id(post_id: int) -> str:
            post = posts.get(post_id)
            return f"post_{_urn_tail(post.urn)}" if post else ""

        repo = Repo(ctx.db)
        created = skipped = 0

        for post_id, vector in all_embeddings:
            similar = find_similar(
                vector,
                all_embeddings,
                top_k=TOP_K_PER_POST,
                exclude_post_id=post_id,
            )
            src_nid = _node_id(post_id)
            src_node = nodes.get(src_nid)
            if not src_node:
                continue

            for other_post_id, score in similar:
                if score < self._threshold:
                    break  # sorted descending, so we can stop early
                tgt_nid = _node_id(other_post_id)
                tgt_node = nodes.get(tgt_nid)
                if not tgt_node:
                    continue
                try:
                    await repo.upsert_graph_edge(
                        source_node_id=src_node.id,
                        target_node_id=tgt_node.id,
                        relation="similar",
                        confidence_score=round(float(score), 4),
                        confidence_tag="EMBEDDING",
                    )
                    created += 1
                except Exception as exc:
                    logger.warning("semantic_edges.edge_failed", error=str(exc))
                    skipped += 1

        await ctx.db.commit()
        logger.info("semantic_edges.complete", created=created, skipped=skipped)
        return StageOutput(stage=self.name, processed=created, skipped=skipped)

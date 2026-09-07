"""Graph build agent: create graph nodes/edges from classified posts."""

from __future__ import annotations

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.knowledge.graph import GraphBuilder
from socialgraph.knowledge.obsidian import _slug, _urn_tail
from socialgraph.storage.enums import PostStatus
from socialgraph.storage.models import GraphEdge, GraphNode, Post, PostTopic, Topic
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)


class GraphBuildAgent:
    name = "graph_build"

    async def run(self, ctx: StageContext) -> StageOutput:
        result = await ctx.db.scalars(
            select(Post)
            .where(Post.status == PostStatus.CLASSIFIED.value)
            .options(selectinload(Post.post_topics).selectinload(PostTopic.topic))
        )
        posts = list(result.all())

        if not posts:
            return StageOutput(stage=self.name, skipped=1, meta={"reason": "no classified posts"})

        repo = Repo(ctx.db)
        builder = GraphBuilder()

        # Ensure topic nodes exist first
        topics_result = await ctx.db.scalars(select(Topic))
        for topic in topics_result.all():
            builder.upsert_topic_node(topic.name, topic.description or "")
            await repo.upsert_graph_node(
                node_id=_slug(topic.name), node_type="topic", label=topic.name
            )

        processed = 0
        for post in posts:
            urn_tail = _urn_tail(post.urn)
            post_node_id = f"post_{urn_tail}"

            db_node = await repo.upsert_graph_node(
                node_id=post_node_id, node_type="post", label=post.author or "Unknown"
            )

            # A force-reclassification replaces topic assignments. Remove the cached
            # classification edges before recreating them so old topics cannot linger.
            await ctx.db.execute(
                delete(GraphEdge).where(
                    GraphEdge.source_node_id == db_node.id,
                    GraphEdge.relation == "conceptually_related_to",
                )
            )

            for pt in post.post_topics:
                topic_node = await ctx.db.scalar(
                    select(GraphNode).where(GraphNode.node_id == _slug(pt.topic.name))
                )
                if topic_node:
                    await repo.upsert_graph_edge(
                        source_node_id=db_node.id,
                        target_node_id=topic_node.id,
                        relation="conceptually_related_to",
                        confidence_score=pt.confidence_score,
                        confidence_tag=pt.confidence_tag,
                    )

            post.status = PostStatus.GRAPHED.value
            processed += 1

        await ctx.db.commit()
        logger.info("graph_build.complete", processed=processed)
        return StageOutput(stage=self.name, processed=processed)

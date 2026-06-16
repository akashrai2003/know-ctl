"""Async repository layer for database operations.

Provides a thin data-access abstraction over SQLAlchemy ``AsyncSession``,
encapsulating common get-or-create, upsert, and query patterns.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.storage.enums import FetchStatus, PostStatus
from socialgraph.storage.models import (
    Author,
    Comment,
    Embedding,
    ExternalLink,
    GraphEdge,
    GraphNode,
    PipelineRun,
    Post,
    PostExternalLink,
    PostSubtopic,
    PostTopic,
    StageCheckpoint,
    Topic,
)

UTC = timezone.utc


class Repo:
    """Thin async data-access layer wrapping SQLAlchemy AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """Expose the underlying session for flush/get operations."""
        return self._session

    async def flush(self) -> None:
        """Flush pending changes to the database."""
        await self._session.flush()

    async def get(self, entity_class: type, pk: Any) -> Any:
        """Get an entity by its primary key."""
        return await self._session.get(entity_class, pk)

    # ── Post ─────────────────────────────────────────────────────────────

    async def get_or_create_post(self, urn: str, platform: str = "linkedin") -> tuple[Post, bool]:
        """Get an existing post by URN or create a new one.

        Args:
            urn: The unique platform URN of the post.
            platform: The social platform name (defaults to 'linkedin').

        Returns:
            A tuple of (Post instance, created_bool).
        """
        existing = await self._session.scalar(select(Post).where(Post.urn == urn))
        if existing:
            return existing, False
        post = Post(urn=urn, platform=platform)
        self._session.add(post)
        await self._session.flush()
        return post, True

    async def get_posts_by_status(self, status: str) -> list[Post]:
        """Fetch all posts matching a specific processing status.

        Args:
            status: The status string (e.g., 'pending', 'ingested').

        Returns:
            A list of matching Post instances.
        """
        result = await self._session.scalars(select(Post).where(Post.status == status))
        return list(result.all())

    async def get_all_posts(self) -> list[Post]:
        """Fetch all posts in the database.

        Returns:
            A list of all Post instances.
        """
        result = await self._session.scalars(select(Post))
        return list(result.all())

    async def count_posts_by_status(self) -> dict[str, int]:
        """Count how many posts exist in each status.

        Returns:
            A dictionary mapping status string to count.
        """
        posts = await self.get_all_posts()
        counts: dict[str, int] = {}
        for p in posts:
            counts[p.status] = counts.get(p.status, 0) + 1
        return counts

    # ── Topic ─────────────────────────────────────────────────────────────

    async def get_or_create_topic(self, name: str) -> tuple[Topic, bool]:
        """Get an existing topic by name or create a new one.

        Args:
            name: The name of the topic.

        Returns:
            A tuple of (Topic instance, created_bool).
        """
        existing = await self._session.scalar(select(Topic).where(Topic.name == name))
        if existing:
            return existing, False
        topic = Topic(name=name)
        self._session.add(topic)
        await self._session.flush()
        return topic, True

    async def get_all_topics(self) -> list[Topic]:
        """Fetch all topics, sorted alphabetically by name.

        Returns:
            A list of sorted Topic instances.
        """
        result = await self._session.scalars(select(Topic).order_by(Topic.name))
        return list(result.all())

    # ── ExternalLink ──────────────────────────────────────────────────────

    async def get_or_create_external_link(self, url: str) -> tuple[ExternalLink, bool]:
        """Get an existing external link by URL or create a new one.

        Uses INSERT OR IGNORE to prevent race conditions during concurrent runs.

        Args:
            url: The target URL.

        Returns:
            A tuple of (ExternalLink instance, created_bool).
        """
        # Check first (fast path for existing rows)
        existing = await self._session.scalar(select(ExternalLink).where(ExternalLink.url == url))
        if existing:
            return existing, False
        # INSERT OR IGNORE avoids UNIQUE violations when concurrent tasks race on the same URL
        stmt = sqlite_insert(ExternalLink).values(url=url, fetch_status="pending")
        stmt = stmt.on_conflict_do_nothing(index_elements=["url"])
        await self._session.execute(stmt)
        await self._session.flush()
        link = await self._session.scalar(select(ExternalLink).where(ExternalLink.url == url))
        assert link is not None
        return link, True

    async def get_pending_links(self) -> list[ExternalLink]:
        """Fetch all external links whose fetch status is pending.

        Returns:
            A list of pending ExternalLink instances.
        """
        result = await self._session.scalars(
            select(ExternalLink).where(ExternalLink.fetch_status == FetchStatus.PENDING.value)
        )
        return list(result.all())

    # ── PostTopic ─────────────────────────────────────────────────────────

    async def upsert_post_topic(
        self,
        post_id: int,
        topic_id: int,
        confidence_score: float,
        confidence_tag: str,
    ) -> PostTopic:
        """Create or update a PostTopic relationship.

        Args:
            post_id: ID of the post.
            topic_id: ID of the topic.
            confidence_score: Confidence level of association.
            confidence_tag: Tag indicating how association was determined.

        Returns:
            The upserted PostTopic instance.
        """
        existing = await self._session.scalar(
            select(PostTopic).where(
                PostTopic.post_id == post_id,
                PostTopic.topic_id == topic_id,
            )
        )
        if existing:
            existing.confidence_score = confidence_score
            existing.confidence_tag = confidence_tag
            return existing
        pt = PostTopic(
            post_id=post_id,
            topic_id=topic_id,
            confidence_score=confidence_score,
            confidence_tag=confidence_tag,
        )
        self._session.add(pt)
        await self._session.flush()
        return pt

    # ── PostSubtopic ──────────────────────────────────────────────────────

    async def upsert_post_subtopic(
        self,
        post_id: int,
        topic_id: int,
        subtopic_name: str,
    ) -> PostSubtopic:
        """Create or update a PostSubtopic relationship.

        Args:
            post_id: ID of the post.
            topic_id: ID of the parent topic.
            subtopic_name: The subtopic classification label.

        Returns:
            The upserted PostSubtopic instance.
        """
        existing = await self._session.scalar(
            select(PostSubtopic).where(
                PostSubtopic.post_id == post_id,
                PostSubtopic.topic_id == topic_id,
            )
        )
        if existing:
            existing.subtopic_name = subtopic_name
            return existing
        ps = PostSubtopic(
            post_id=post_id,
            topic_id=topic_id,
            subtopic_name=subtopic_name,
            created_at=datetime.now(UTC),
        )
        self._session.add(ps)
        await self._session.flush()
        return ps

    async def rename_subtopic_in_topic(
        self,
        old_name: str,
        new_name: str,
        topic_id: int,
    ) -> int:
        """Rename all PostSubtopic rows with old_name in a topic to new_name. Returns count."""
        result = await self._session.execute(
            update(PostSubtopic)
            .where(PostSubtopic.topic_id == topic_id, PostSubtopic.subtopic_name == old_name)
            .values(subtopic_name=new_name)
        )
        return result.rowcount  # type: ignore[attr-defined]

    # ── Author ────────────────────────────────────────────────────────────

    async def get_or_create_author(self, name: str, slug: str) -> tuple[Author, bool]:
        """Get an existing author by their slug or create a new one.

        Args:
            name: The display name of the author.
            slug: The unique ASCII slug for the author.

        Returns:
            A tuple of (Author instance, created_bool).
        """
        existing = await self._session.scalar(select(Author).where(Author.slug == slug))
        if existing:
            return existing, False
        author = Author(name=name, slug=slug)
        self._session.add(author)
        await self._session.flush()
        return author, True

    # ── GraphNode / GraphEdge ─────────────────────────────────────────────

    async def upsert_graph_node(self, node_id: str, node_type: str, label: str) -> GraphNode:
        """Insert or update a graph node in the cached graph representation.

        Args:
            node_id: Unique identifier for the node.
            node_type: Node type (e.g. 'post', 'topic').
            label: Text label of the node.

        Returns:
            The upserted GraphNode instance.
        """
        existing = await self._session.scalar(select(GraphNode).where(GraphNode.node_id == node_id))
        if existing:
            existing.label = label
            return existing
        node = GraphNode(node_id=node_id, node_type=node_type, label=label)
        self._session.add(node)
        await self._session.flush()
        return node

    async def upsert_graph_edge(
        self,
        source_node_id: int,
        target_node_id: int,
        relation: str,
        confidence_score: float = 1.0,
        confidence_tag: str = "EXTRACTED",
    ) -> GraphEdge:
        """Insert or update a directed graph edge.

        Args:
            source_node_id: Primary key of source GraphNode.
            target_node_id: Primary key of target GraphNode.
            relation: Label/relationship type.
            confidence_score: Strength of connection (defaults to 1.0).
            confidence_tag: Source of edge ('EXTRACTED', 'INFERRED', etc.).

        Returns:
            The upserted GraphEdge instance.
        """
        existing = await self._session.scalar(
            select(GraphEdge).where(
                GraphEdge.source_node_id == source_node_id,
                GraphEdge.target_node_id == target_node_id,
                GraphEdge.relation == relation,
            )
        )
        if existing:
            existing.confidence_score = confidence_score
            existing.confidence_tag = confidence_tag
            return existing
        edge = GraphEdge(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relation=relation,
            confidence_score=confidence_score,
            confidence_tag=confidence_tag,
        )
        self._session.add(edge)
        await self._session.flush()
        return edge

    # ── PipelineRun / StageCheckpoint ─────────────────────────────────────

    async def create_pipeline_run(self, run_id: str) -> PipelineRun:
        """Record the start of a pipeline run execution.

        Args:
            run_id: A unique identifier for the run.

        Returns:
            The created PipelineRun instance.
        """
        run = PipelineRun(run_id=run_id, status="running")
        self._session.add(run)
        await self._session.flush()
        return run

    async def get_pipeline_run(self, run_id: str) -> PipelineRun | None:
        """Fetch a pipeline run record by its run ID.

        Args:
            run_id: The unique run identifier.

        Returns:
            The PipelineRun if found, else None.
        """
        return await self._session.scalar(select(PipelineRun).where(PipelineRun.run_id == run_id))

    async def has_checkpoint(self, run_id: str, stage: str, input_hash: str) -> bool:
        """Check if a pipeline stage checkpoint completed successfully.

        Args:
            run_id: The active pipeline run ID.
            stage: The name of the pipeline stage.
            input_hash: Hash of the inputs to detect changes.

        Returns:
            True if a successful checkpoint exists, else False.
        """
        row = await self._session.scalar(
            select(StageCheckpoint).where(
                StageCheckpoint.run_id == run_id,
                StageCheckpoint.stage == stage,
                StageCheckpoint.input_hash == input_hash,
                StageCheckpoint.status == PostStatus.OK.value,
            )
        )
        return row is not None

    async def write_checkpoint(
        self, run_id: str, stage: str, input_hash: str, status: str, meta: dict
    ) -> StageCheckpoint:
        """Write a new checkpoint record for idempotency.

        Args:
            run_id: The active pipeline run ID.
            stage: The name of the pipeline stage.
            input_hash: Hash of the stage inputs.
            status: Execution status ('ok', 'failed').
            meta: Key-value metadata dictionary.

        Returns:
            The created StageCheckpoint instance.
        """
        ckpt = StageCheckpoint(
            run_id=run_id,
            stage=stage,
            input_hash=input_hash,
            status=status,
            meta_json=json.dumps(meta),
            completed_at=datetime.now(UTC),
        )
        self._session.add(ckpt)
        await self._session.flush()
        return ckpt

    # ── PostExternalLink ──────────────────────────────────────────────────

    async def link_post_to_url(
        self, post_id: int, external_link_id: int, context: str = "body"
    ) -> PostExternalLink:
        """Link an external URL to a post.

        Args:
            post_id: ID of the post.
            external_link_id: ID of the external link.
            context: The context where it was found ('body', 'comment').

        Returns:
            The linked PostExternalLink instance.
        """
        existing = await self._session.scalar(
            select(PostExternalLink).where(
                PostExternalLink.post_id == post_id,
                PostExternalLink.external_link_id == external_link_id,
            )
        )
        if existing:
            return existing
        pel = PostExternalLink(post_id=post_id, external_link_id=external_link_id, context=context)
        self._session.add(pel)
        await self._session.flush()
        return pel

    async def link_comment_url(
        self, post_id: int, external_link_id: int, comment_id: int
    ) -> PostExternalLink | None:
        """Link a URL sourced from a comment to the post.

        Returns None (without inserting) if the URL is already linked to this
        post from any source — avoids duplicating links already captured from
        the post body.
        """
        existing = await self._session.scalar(
            select(PostExternalLink).where(
                PostExternalLink.post_id == post_id,
                PostExternalLink.external_link_id == external_link_id,
            )
        )
        if existing:
            return None
        pel = PostExternalLink(
            post_id=post_id,
            external_link_id=external_link_id,
            context="comment",
            comment_id=comment_id,
        )
        self._session.add(pel)
        await self._session.flush()
        return pel

    # ── Comment ───────────────────────────────────────────────────────────

    async def get_posts_needing_comments(self, limit: int = 0) -> list[Post]:
        """Fetch posts that haven't had comments fetched yet.

        Args:
            limit: Maximum number of posts to fetch (0 for unlimited).

        Returns:
            A list of Post instances.
        """
        q = select(Post).where(
            Post.comments_fetched == False,  # noqa: E712
            Post.status.in_(["ok", "graphed", "enriched", "classified"]),
        )
        if limit:
            q = q.limit(limit)
        result = await self._session.scalars(q)
        return list(result.all())

    async def bulk_insert_comments(self, post_id: int, comments: list[dict]) -> int:
        """Insert comments for a post; skip if post already has comments with matching rank."""
        existing_ranks = set(
            await self._session.scalars(select(Comment.rank).where(Comment.post_id == post_id))
        )
        added = 0
        for rank, c in enumerate(comments):
            if rank in existing_ranks:
                continue
            obj = Comment(
                post_id=post_id,
                author=c.get("author"),
                text=c.get("text", ""),
                has_external_url=bool(c.get("has_external_url", False)),
                rank=rank,
                is_reply=bool(c.get("is_reply", False)),
                comment_urn=c.get("comment_urn") or None,
                parent_comment_urn=c.get("parent_comment_urn") or None,
                created_at=datetime.now(UTC),
            )
            self._session.add(obj)
            added += 1
        await self._session.flush()
        return added

    async def delete_comments_for_post(self, post_id: int) -> int:
        """Delete all comments for a post (used by --force re-scrape). Returns count deleted."""
        result = await self._session.execute(delete(Comment).where(Comment.post_id == post_id))
        await self._session.flush()
        return result.rowcount  # type: ignore[attr-defined]

    # ── Embedding ─────────────────────────────────────────────────────────

    async def upsert_embedding(
        self, post_id: int, vector_json: str, model: str, dim: int
    ) -> Embedding:
        """Insert or update post embedding vectors.

        Args:
            post_id: ID of the associated post.
            vector_json: Serialized JSON float array representing the vector.
            model: Model name used to generate the embedding.
            dim: Dimension of the embedding vector.

        Returns:
            The upserted Embedding instance.
        """
        existing = await self._session.scalar(select(Embedding).where(Embedding.post_id == post_id))
        if existing:
            existing.vector_json = vector_json
            existing.model = model
            existing.dim = dim
            return existing
        emb = Embedding(
            post_id=post_id,
            vector_json=vector_json,
            model=model,
            dim=dim,
            created_at=datetime.now(UTC),
        )
        self._session.add(emb)
        await self._session.flush()
        return emb

    async def get_all_embeddings(self) -> list[Embedding]:
        """Fetch all post embedding records from the database.

        Returns:
            A list of all Embedding instances.
        """
        result = await self._session.scalars(select(Embedding))
        return list(result.all())

    async def get_posts_without_embeddings(self) -> list[Post]:
        """Return posts that have no Embedding row yet.

        Returns:
            A list of Post instances lacking embeddings.
        """
        subq = select(Embedding.post_id)
        result = await self._session.scalars(select(Post).where(Post.id.not_in(subq)))
        return list(result.all())

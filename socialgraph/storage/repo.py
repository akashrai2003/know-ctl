from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

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


class Repo:
    """Thin async data-access layer wrapping SQLAlchemy AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ── Post ─────────────────────────────────────────────────────────────

    async def get_or_create_post(self, urn: str, platform: str = "linkedin") -> tuple[Post, bool]:
        existing = await self._s.scalar(select(Post).where(Post.urn == urn))
        if existing:
            return existing, False
        post = Post(urn=urn, platform=platform)
        self._s.add(post)
        await self._s.flush()
        return post, True

    async def get_posts_by_status(self, status: str) -> list[Post]:
        result = await self._s.scalars(select(Post).where(Post.status == status))
        return list(result.all())

    async def get_all_posts(self) -> list[Post]:
        result = await self._s.scalars(select(Post))
        return list(result.all())

    async def count_posts_by_status(self) -> dict[str, int]:
        posts = await self.get_all_posts()
        counts: dict[str, int] = {}
        for p in posts:
            counts[p.status] = counts.get(p.status, 0) + 1
        return counts

    # ── Topic ─────────────────────────────────────────────────────────────

    async def get_or_create_topic(self, name: str) -> tuple[Topic, bool]:
        existing = await self._s.scalar(select(Topic).where(Topic.name == name))
        if existing:
            return existing, False
        topic = Topic(name=name)
        self._s.add(topic)
        await self._s.flush()
        return topic, True

    async def get_all_topics(self) -> list[Topic]:
        result = await self._s.scalars(select(Topic).order_by(Topic.name))
        return list(result.all())

    # ── ExternalLink ──────────────────────────────────────────────────────

    async def get_or_create_external_link(self, url: str) -> tuple[ExternalLink, bool]:
        # Check first (fast path for existing rows)
        existing = await self._s.scalar(select(ExternalLink).where(ExternalLink.url == url))
        if existing:
            return existing, False
        # INSERT OR IGNORE avoids UNIQUE violations when concurrent tasks race on the same URL
        stmt = sqlite_insert(ExternalLink).values(url=url, fetch_status="pending")
        stmt = stmt.on_conflict_do_nothing(index_elements=["url"])
        await self._s.execute(stmt)
        await self._s.flush()
        link = await self._s.scalar(select(ExternalLink).where(ExternalLink.url == url))
        return link, True

    async def get_pending_links(self) -> list[ExternalLink]:
        result = await self._s.scalars(
            select(ExternalLink).where(ExternalLink.fetch_status == "pending")
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
        existing = await self._s.scalar(
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
        self._s.add(pt)
        await self._s.flush()
        return pt

    # ── PostSubtopic ──────────────────────────────────────────────────────

    async def upsert_post_subtopic(
        self,
        post_id: int,
        topic_id: int,
        subtopic_name: str,
    ) -> PostSubtopic:
        from datetime import datetime

        existing = await self._s.scalar(
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
            created_at=datetime.utcnow(),
        )
        self._s.add(ps)
        await self._s.flush()
        return ps

    async def rename_subtopic_in_topic(
        self,
        old_name: str,
        new_name: str,
        topic_id: int,
    ) -> int:
        """Rename all PostSubtopic rows with old_name in a topic to new_name. Returns count."""
        from sqlalchemy import update

        result = await self._s.execute(
            update(PostSubtopic)
            .where(PostSubtopic.topic_id == topic_id, PostSubtopic.subtopic_name == old_name)
            .values(subtopic_name=new_name)
        )
        return result.rowcount  # type: ignore[return-value]

    # ── Author ────────────────────────────────────────────────────────────

    async def get_or_create_author(self, name: str, slug: str) -> tuple[Author, bool]:
        existing = await self._s.scalar(select(Author).where(Author.slug == slug))
        if existing:
            return existing, False
        author = Author(name=name, slug=slug)
        self._s.add(author)
        await self._s.flush()
        return author, True

    # ── GraphNode / GraphEdge ─────────────────────────────────────────────

    async def upsert_graph_node(self, node_id: str, node_type: str, label: str) -> GraphNode:
        existing = await self._s.scalar(
            select(GraphNode).where(GraphNode.node_id == node_id)
        )
        if existing:
            existing.label = label
            return existing
        node = GraphNode(node_id=node_id, node_type=node_type, label=label)
        self._s.add(node)
        await self._s.flush()
        return node

    async def upsert_graph_edge(
        self,
        source_node_id: int,
        target_node_id: int,
        relation: str,
        confidence_score: float = 1.0,
        confidence_tag: str = "EXTRACTED",
    ) -> GraphEdge:
        existing = await self._s.scalar(
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
        self._s.add(edge)
        await self._s.flush()
        return edge

    # ── PipelineRun / StageCheckpoint ─────────────────────────────────────

    async def create_pipeline_run(self, run_id: str) -> PipelineRun:
        run = PipelineRun(run_id=run_id, status="running")
        self._s.add(run)
        await self._s.flush()
        return run

    async def get_pipeline_run(self, run_id: str) -> PipelineRun | None:
        return await self._s.scalar(
            select(PipelineRun).where(PipelineRun.run_id == run_id)
        )

    async def has_checkpoint(self, run_id: str, stage: str, input_hash: str) -> bool:
        row = await self._s.scalar(
            select(StageCheckpoint).where(
                StageCheckpoint.run_id == run_id,
                StageCheckpoint.stage == stage,
                StageCheckpoint.input_hash == input_hash,
                StageCheckpoint.status == "ok",
            )
        )
        return row is not None

    async def write_checkpoint(
        self, run_id: str, stage: str, input_hash: str, status: str, meta: dict
    ) -> StageCheckpoint:
        import json

        ckpt = StageCheckpoint(
            run_id=run_id,
            stage=stage,
            input_hash=input_hash,
            status=status,
            meta_json=json.dumps(meta),
            completed_at=datetime.utcnow(),
        )
        self._s.add(ckpt)
        await self._s.flush()
        return ckpt

    # ── PostExternalLink ──────────────────────────────────────────────────

    async def link_post_to_url(
        self, post_id: int, external_link_id: int, context: str = "body"
    ) -> PostExternalLink:
        existing = await self._s.scalar(
            select(PostExternalLink).where(
                PostExternalLink.post_id == post_id,
                PostExternalLink.external_link_id == external_link_id,
            )
        )
        if existing:
            return existing
        pel = PostExternalLink(
            post_id=post_id, external_link_id=external_link_id, context=context
        )
        self._s.add(pel)
        await self._s.flush()
        return pel

    async def link_comment_url(
        self, post_id: int, external_link_id: int, comment_id: int
    ) -> PostExternalLink | None:
        """Link a URL sourced from a comment to the post.

        Returns None (without inserting) if the URL is already linked to this
        post from any source — avoids duplicating links already captured from
        the post body.
        """
        existing = await self._s.scalar(
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
        self._s.add(pel)
        await self._s.flush()
        return pel

    # ── Comment ───────────────────────────────────────────────────────────

    async def get_posts_needing_comments(self, limit: int = 0) -> list[Post]:
        q = select(Post).where(
            Post.comments_fetched == False,  # noqa: E712
            Post.status.in_(["ok", "graphed", "enriched", "classified"]),
        )
        if limit:
            q = q.limit(limit)
        result = await self._s.scalars(q)
        return list(result.all())

    async def bulk_insert_comments(
        self, post_id: int, comments: list[dict]
    ) -> int:
        """Insert comments for a post; skip if post already has comments with matching rank."""
        existing_ranks = set(
            await self._s.scalars(
                select(Comment.rank).where(Comment.post_id == post_id)
            )
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
                created_at=datetime.utcnow(),
            )
            self._s.add(obj)
            added += 1
        await self._s.flush()
        return added

    async def delete_comments_for_post(self, post_id: int) -> int:
        """Delete all comments for a post (used by --force re-scrape). Returns count deleted."""
        from sqlalchemy import delete as sql_delete
        result = await self._s.execute(
            sql_delete(Comment).where(Comment.post_id == post_id)
        )
        await self._s.flush()
        return result.rowcount

    # ── Embedding ─────────────────────────────────────────────────────────

    async def upsert_embedding(
        self, post_id: int, vector_json: str, model: str, dim: int
    ) -> Embedding:
        existing = await self._s.scalar(
            select(Embedding).where(Embedding.post_id == post_id)
        )
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
            created_at=datetime.utcnow(),
        )
        self._s.add(emb)
        await self._s.flush()
        return emb

    async def get_all_embeddings(self) -> list[Embedding]:
        result = await self._s.scalars(select(Embedding))
        return list(result.all())

    async def get_posts_without_embeddings(self) -> list[Post]:
        """Return posts that have no Embedding row yet."""
        subq = select(Embedding.post_id)
        result = await self._s.scalars(
            select(Post).where(Post.id.not_in(subq))
        )
        return list(result.all())

"""SQLAlchemy ORM models for the Social Graph database schema."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from socialgraph.storage.enums import FetchStatus, PostStatus

UTC = timezone.utc


def _utc_now() -> datetime:
    """Return a timezone-aware UTC datetime for column defaults."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


class Post(Base):
    """A saved social media post (e.g. from LinkedIn)."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    urn: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="linkedin")
    author: Mapped[str | None] = mapped_column(String(256))
    subtitle: Mapped[str | None] = mapped_column(String(512))
    date_raw: Mapped[str | None] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_url: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PostStatus.PENDING.value
    )
    # stage tracking: pending → ingested → enriched → classified → graphed → ok
    comments_fetched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now, onupdate=_utc_now
    )

    title: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    insight_json: Mapped[str | None] = mapped_column(Text)
    insight_source_hash: Mapped[str | None] = mapped_column(String(64))
    insight_generated_at: Mapped[datetime | None] = mapped_column(DateTime)

    post_topics: Mapped[list[PostTopic]] = relationship("PostTopic", back_populates="post")
    post_subtopics: Mapped[list[PostSubtopic]] = relationship("PostSubtopic", back_populates="post")
    comments: Mapped[list[Comment]] = relationship("Comment", back_populates="post")
    post_links: Mapped[list[PostExternalLink]] = relationship(
        "PostExternalLink", back_populates="post"
    )
    embedding: Mapped[Embedding | None] = relationship(
        "Embedding", back_populates="post", uselist=False
    )


class Topic(Base):
    """A canonical topic in the knowledge taxonomy."""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    aliases_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)

    @property
    def aliases(self) -> list[str]:
        return json.loads(self.aliases_json)

    @aliases.setter
    def aliases(self, value: list[str]) -> None:
        self.aliases_json = json.dumps(value)

    post_topics: Mapped[list[PostTopic]] = relationship("PostTopic", back_populates="topic")


class PostSubtopic(Base):
    """Maps a post to a subtopic within a parent topic."""

    __tablename__ = "post_subtopics"
    __table_args__ = (UniqueConstraint("post_id", "topic_id", name="uq_post_subtopic"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)
    subtopic_name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)

    post: Mapped[Post] = relationship("Post", back_populates="post_subtopics")
    topic: Mapped[Topic] = relationship("Topic")


class PostTopic(Base):
    """Many-to-many association between posts and topics with confidence score."""

    __tablename__ = "post_topics"
    __table_args__ = (UniqueConstraint("post_id", "topic_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence_tag: Mapped[str] = mapped_column(String(32), nullable=False, default="EXTRACTED")

    post: Mapped[Post] = relationship("Post", back_populates="post_topics")
    topic: Mapped[Topic] = relationship("Topic", back_populates="post_topics")


class Author(Base):
    """Aggregated author profile derived from posts."""

    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(512))
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="linkedin")
    post_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)


class ExternalLink(Base):
    """An external URL referenced in a post or comment."""

    __tablename__ = "external_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text)
    body_excerpt: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, default="article")
    fetch_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FetchStatus.PENDING.value
    )
    error_reason: Mapped[str | None] = mapped_column(String(256))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)

    post_links: Mapped[list[PostExternalLink]] = relationship(
        "PostExternalLink", back_populates="external_link"
    )


class PostExternalLink(Base):
    """Many-to-many: Post ↔ ExternalLink"""

    __tablename__ = "post_external_links"
    __table_args__ = (UniqueConstraint("post_id", "external_link_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    external_link_id: Mapped[int] = mapped_column(ForeignKey("external_links.id"), nullable=False)
    context: Mapped[str] = mapped_column(String(32), nullable=False, default="body")
    # context: "body" | "comment"
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True)

    post: Mapped[Post] = relationship("Post", back_populates="post_links")
    external_link: Mapped[ExternalLink] = relationship("ExternalLink", back_populates="post_links")


class Comment(Base):
    """A comment on a post, scraped from LinkedIn."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    author: Mapped[str | None] = mapped_column(String(256))
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    has_external_url: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    urls_enriched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # ordering
    # Nested-comment fields — populated when using the Voyager API scraper
    is_reply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    comment_urn: Mapped[str | None] = mapped_column(String(512), nullable=True)
    parent_comment_urn: Mapped[str | None] = mapped_column(String(512), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    usefulness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)

    post: Mapped[Post] = relationship("Post", back_populates="comments")


class GraphNode(Base):
    """A node in the knowledge graph (post or topic)."""

    __tablename__ = "graph_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    community: Mapped[str | None] = mapped_column(String(128))
    meta_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)

    out_edges: Mapped[list[GraphEdge]] = relationship(
        "GraphEdge", foreign_keys="GraphEdge.source_node_id", back_populates="source_node"
    )
    in_edges: Mapped[list[GraphEdge]] = relationship(
        "GraphEdge", foreign_keys="GraphEdge.target_node_id", back_populates="target_node"
    )


class GraphEdge(Base):
    """A directed edge in the knowledge graph."""

    __tablename__ = "graph_edges"
    __table_args__ = (UniqueConstraint("source_node_id", "target_node_id", "relation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_node_id: Mapped[int] = mapped_column(ForeignKey("graph_nodes.id"), nullable=False)
    target_node_id: Mapped[int] = mapped_column(ForeignKey("graph_nodes.id"), nullable=False)
    relation: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence_tag: Mapped[str] = mapped_column(String(32), nullable=False, default="EXTRACTED")

    source_node: Mapped[GraphNode] = relationship(
        "GraphNode", foreign_keys=[source_node_id], back_populates="out_edges"
    )
    target_node: Mapped[GraphNode] = relationship(
        "GraphNode", foreign_keys=[target_node_id], back_populates="in_edges"
    )


class PipelineRun(Base):
    """Record of a single pipeline execution."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    stage_counts_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    checkpoints: Mapped[list[StageCheckpoint]] = relationship(
        "StageCheckpoint", back_populates="run"
    )


class StageCheckpoint(Base):
    """Checkpoint record for idempotent stage re-runs."""

    __tablename__ = "stage_checkpoints"
    __table_args__ = (UniqueConstraint("run_id", "stage", "input_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("pipeline_runs.run_id"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    meta_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    run: Mapped[PipelineRun] = relationship("PipelineRun", back_populates="checkpoints")


class Embedding(Base):
    """Stores post embedding vectors as JSON float arrays."""

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id"), unique=True, nullable=False, index=True
    )
    vector_json: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)

    post: Mapped[Post] = relationship("Post", back_populates="embedding")

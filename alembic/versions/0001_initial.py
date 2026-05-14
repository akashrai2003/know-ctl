"""Initial schema — all tables.

Revision ID: 0001
Revises:
Create Date: 2025-01-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("urn", sa.String(128), nullable=False, unique=True, index=True),
        sa.Column("platform", sa.String(32), nullable=False, default="linkedin"),
        sa.Column("author", sa.String(256)),
        sa.Column("subtitle", sa.String(512)),
        sa.Column("date_raw", sa.String(128)),
        sa.Column("content", sa.Text(), nullable=False, default=""),
        sa.Column("source_url", sa.String(1024)),
        sa.Column("status", sa.String(32), nullable=False, default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("aliases_json", sa.Text(), nullable=False, default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "post_topics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False, default=1.0),
        sa.Column("confidence_tag", sa.String(32), nullable=False, default="EXTRACTED"),
        sa.UniqueConstraint("post_id", "topic_id"),
    )
    op.create_table(
        "authors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("slug", sa.String(256), unique=True, nullable=False),
        sa.Column("subtitle", sa.String(512)),
        sa.Column("platform", sa.String(32), nullable=False, default="linkedin"),
        sa.Column("post_count", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "external_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("url", sa.String(2048), nullable=False, unique=True, index=True),
        sa.Column("title", sa.String(1024)),
        sa.Column("description", sa.Text()),
        sa.Column("body_excerpt", sa.Text()),
        sa.Column("content_type", sa.String(32), nullable=False, default="article"),
        sa.Column("fetch_status", sa.String(32), nullable=False, default="pending"),
        sa.Column("error_reason", sa.String(256)),
        sa.Column("fetched_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "post_external_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("external_link_id", sa.Integer(), sa.ForeignKey("external_links.id"), nullable=False),
        sa.Column("context", sa.String(32), nullable=False, default="body"),
        sa.UniqueConstraint("post_id", "external_link_id"),
    )
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("author", sa.String(256)),
        sa.Column("text", sa.Text(), nullable=False, default=""),
        sa.Column("has_external_url", sa.Boolean(), nullable=False, default=False),
        sa.Column("rank", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("node_id", sa.String(256), nullable=False, unique=True, index=True),
        sa.Column("node_type", sa.String(32), nullable=False),
        sa.Column("label", sa.String(512), nullable=False),
        sa.Column("community", sa.String(128)),
        sa.Column("meta_json", sa.Text(), nullable=False, default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "graph_edges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_node_id", sa.Integer(), sa.ForeignKey("graph_nodes.id"), nullable=False),
        sa.Column("target_node_id", sa.Integer(), sa.ForeignKey("graph_nodes.id"), nullable=False),
        sa.Column("relation", sa.String(64), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False, default=1.0),
        sa.Column("confidence_tag", sa.String(32), nullable=False, default="EXTRACTED"),
        sa.UniqueConstraint("source_node_id", "target_node_id", "relation"),
    )
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("status", sa.String(32), nullable=False, default="running"),
        sa.Column("stage_counts_json", sa.Text(), nullable=False, default="{}"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_table(
        "stage_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("pipeline_runs.run_id"), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, default="pending"),
        sa.Column("meta_json", sa.Text(), nullable=False, default="{}"),
        sa.Column("completed_at", sa.DateTime()),
        sa.UniqueConstraint("run_id", "stage", "input_hash"),
    )


def downgrade() -> None:
    op.drop_table("stage_checkpoints")
    op.drop_table("pipeline_runs")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
    op.drop_table("comments")
    op.drop_table("post_external_links")
    op.drop_table("external_links")
    op.drop_table("authors")
    op.drop_table("post_topics")
    op.drop_table("topics")
    op.drop_table("posts")

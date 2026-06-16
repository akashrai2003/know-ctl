"""Add Embedding table, Post.comments_fetched, ExternalLink.ai_summary.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("comments_fetched", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("external_links", sa.Column("ai_summary", sa.Text(), nullable=True))
    op.create_table(
        "embeddings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False, unique=True),
        sa.Column("vector_json", sa.Text(), nullable=False),
        sa.Column("model", sa.String(256), nullable=False, server_default=""),
        sa.Column("dim", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_embeddings_post_id", "embeddings", ["post_id"])


def downgrade() -> None:
    op.drop_index("ix_embeddings_post_id", "embeddings")
    op.drop_table("embeddings")
    op.drop_column("external_links", "ai_summary")
    op.drop_column("posts", "comments_fetched")

"""Add Post.title and post_subtopics table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("title", sa.Text(), nullable=True))
    op.create_table(
        "post_subtopics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("subtopic_name", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("post_id", "topic_id", name="uq_post_subtopic"),
    )


def downgrade() -> None:
    op.drop_table("post_subtopics")
    op.drop_column("posts", "title")

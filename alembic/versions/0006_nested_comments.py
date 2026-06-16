"""Add nested-comment fields: is_reply, parent_comment_urn, comment_urn.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Whether this comment is a reply to another comment
    op.add_column(
        "comments",
        sa.Column("is_reply", sa.Boolean(), nullable=False, server_default="0"),
    )
    # LinkedIn URN of this specific comment (e.g. urn:li:comment:(urn:li:activity:X,Y))
    op.add_column(
        "comments",
        sa.Column("comment_urn", sa.String(512), nullable=True),
    )
    # LinkedIn URN of the parent comment this is a reply to (null for top-level)
    op.add_column(
        "comments",
        sa.Column("parent_comment_urn", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("comments", "parent_comment_urn")
    op.drop_column("comments", "comment_urn")
    op.drop_column("comments", "is_reply")

"""Add Comment.urls_enriched and PostExternalLink.comment_id for comment URL enrichment.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Track whether a comment's URLs have been enriched
    op.add_column(
        "comments",
        sa.Column("urls_enriched", sa.Boolean(), nullable=False, server_default="0"),
    )
    # Optional back-reference: which comment produced this post↔link row
    # Note: SQLite does not support adding FK constraints via ALTER TABLE —
    # the FK relationship is enforced at the ORM/application layer only.
    op.add_column(
        "post_external_links",
        sa.Column("comment_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("post_external_links", "comment_id")
    op.drop_column("comments", "urls_enriched")

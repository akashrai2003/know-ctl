"""Add comment ranking fields and post insight_json.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("comments", sa.Column("kind", sa.String(32), nullable=True))
    op.add_column(
        "comments",
        sa.Column("usefulness_score", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column("posts", sa.Column("insight_json", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("insight_source_hash", sa.String(64), nullable=True))
    op.add_column("posts", sa.Column("insight_generated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "insight_generated_at")
    op.drop_column("posts", "insight_source_hash")
    op.drop_column("posts", "insight_json")
    op.drop_column("comments", "usefulness_score")
    op.drop_column("comments", "kind")

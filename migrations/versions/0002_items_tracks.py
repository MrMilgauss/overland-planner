"""items and tracks

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_index("ix_items_project_id", "items", ["project_id"])
    op.create_table(
        "tracks",
        sa.Column("item_id", sa.Text(), sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("original_sha256", sa.Text(), nullable=False),
        sa.Column("direction_version", sa.Integer(), nullable=False),
        sa.Column("canonical_sha256", sa.Text(), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("entry_lat", sa.Float(), nullable=False),
        sa.Column("entry_lon", sa.Float(), nullable=False),
        sa.Column("exit_lat", sa.Float(), nullable=False),
        sa.Column("exit_lon", sa.Float(), nullable=False),
        sa.Column("length_m", sa.Float(), nullable=False),
        sa.Column("elevation_gain_m", sa.Float(), nullable=True),
        sa.Column("elevation_loss_m", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    """Every revision has a CI-tested downgrade (DV-5); the files under files/ are left for the orphan sweep."""
    op.drop_table("tracks")
    op.drop_index("ix_items_project_id", table_name="items")
    op.drop_table("items")

"""pois

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pois",
        sa.Column("item_id", sa.Text(), sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    """Every revision has a CI-tested downgrade (DV-5). The POIs' `items` rows go with their details."""
    op.execute("DELETE FROM items WHERE type = 'poi'")
    op.drop_table("pois")

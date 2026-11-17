"""plan run profile

Slice 06a: `plan_runs.profile` (ADR-013 Amendment 4, D250), the way the road map routed (`4x4.v1`, `mock.v1`), stored
with every new run so that the results can name it. A run stored before reads none.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Added in place (`ADD COLUMN`), so `plan_runs` is not rebuilt and every stored run stays (brief §9)."""
    op.add_column("plan_runs", sa.Column("profile", sa.Text(), nullable=True))


def downgrade() -> None:
    """SQLite drops the column by rebuilding `plan_runs` (batch mode), as 0008 does; every run stays."""
    with op.batch_alter_table("plan_runs") as batch:
        batch.drop_column("profile")

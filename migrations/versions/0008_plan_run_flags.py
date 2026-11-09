"""plan run flags

Slice 03's one revision for `plan_runs` (brief section 8 run flags, D42): `reproducible` (true for every run stored
before: its search ended on the budget) and `not_fully_optimised` (time_limit, stopped, optimizer_failed or null),
filled from 06-06; `run_time_ms` and `memo_source_run_id` stay null until 06-10 writes them.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NULLABLE_COLUMNS = (
    ("not_fully_optimised", sa.Text()),
    ("run_time_ms", sa.Integer()),
    ("memo_source_run_id", sa.Text()),
)


def upgrade() -> None:
    """Added in place (`ADD COLUMN`), so `plan_runs` is not rebuilt and every stored run stays (brief §9)."""
    op.add_column("plan_runs", sa.Column("reproducible", sa.Boolean(), nullable=False, server_default=sa.true()))
    for name, type_ in _NULLABLE_COLUMNS:
        op.add_column("plan_runs", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    """SQLite drops the columns by rebuilding `plan_runs` (batch mode), as 0006 does; every run stays."""
    with op.batch_alter_table("plan_runs") as batch:
        for name in ("reproducible", *(name for name, _ in _NULLABLE_COLUMNS)):
            batch.drop_column(name)

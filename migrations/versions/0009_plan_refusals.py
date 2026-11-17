"""plan refusals

Slice 06a: the append-only `plan_refusals` (ADR-013 Amendment 4, D248), one row per refused plan request; the
diagnostics count the routing engine's from it (kpi-contracts G4). The table only; its downgrade drops it, and nothing
else changes.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No foreign key: the log outlives a deleted project (append-only, G4 reads it)."""
    op.create_table(
        "plan_refusals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    """CI-tested downgrade (DV-5): nothing references the table, so dropping it changes nothing else."""
    op.drop_table("plan_refusals")

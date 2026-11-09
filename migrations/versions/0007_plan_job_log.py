"""plan job log

Slice 03-ops: the append-only `plan_job_log` (ADR-015 DV-2, D93), one row per job that reached its end. The table only;
its downgrade drops it, and nothing else changes.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NULLABLE = (
    ("plan_run_id", sa.Text()),
    ("items_included", sa.Integer()),
    ("legs_total", sa.Integer()),
    ("legs_new", sa.Integer()),
    ("legs_cached", sa.Integer()),
    ("points_new", sa.Integer()),
    ("second_pass_pairs", sa.Integer()),
    ("retried", sa.Boolean()),
    ("stage_ms", sa.JSON()),
    ("solver_solutions", sa.Integer()),
    ("incumbents", sa.Integer()),
    ("reproducible", sa.Boolean()),
    ("not_fully_optimised_reason", sa.Text()),
    ("unconfirmed_legs", sa.Integer()),
    ("retraces", sa.Integer()),
    ("solver_wait_s", sa.Float()),
    ("provider_id", sa.Text()),
    ("error_class", sa.Text()),
    ("reason", sa.Text()),
)


def upgrade() -> None:
    """No foreign key: the log outlives a deleted project and a run (append-only, K5/K7 read it)."""
    op.create_table(
        "plan_job_log",
        sa.Column("job_id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_state", sa.Text(), nullable=False),
        sa.Column("memo_hit", sa.Boolean(), nullable=False),
        sa.Column("ignore_memo", sa.Boolean(), nullable=False),
        sa.Column("app_version", sa.Text(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        *(sa.Column(name, type_, nullable=True) for name, type_ in _NULLABLE),
    )


def downgrade() -> None:
    """CI-tested downgrade (DV-5): nothing references the log, so dropping it changes nothing else."""
    op.drop_table("plan_job_log")

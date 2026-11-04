"""plan runs

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The numbered plan runs of a project (brief §9). Later slices add the columns they fill, each in its revision."""
    op.create_table(
        "plan_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("itinerary", sa.JSON(), nullable=True),
        sa.UniqueConstraint("project_id", "number", name="uq_plan_runs_project_id_number"),
    )


def downgrade() -> None:
    """Every revision has a CI-tested downgrade (DV-5). Nothing references `plan_runs`, so projects and items stay."""
    op.drop_table("plan_runs")

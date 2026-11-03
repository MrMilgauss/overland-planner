"""project anchors

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ANCHOR_COLUMNS = ("start_item_id", "end_item_id")


def upgrade() -> None:
    """The trip's Start and End POIs (HC-2, brief §9). SQLite adds a referencing column in place (`ADD COLUMN`), so
    the projects table is never rebuilt - a rebuild under the planner's `foreign_keys=ON` would cascade to its items.
    """
    for column in _ANCHOR_COLUMNS:
        op.execute(f"ALTER TABLE projects ADD COLUMN {column} TEXT REFERENCES items (id) ON DELETE SET NULL")


def downgrade() -> None:
    """Every revision has a CI-tested downgrade (DV-5); the operator's `alembic downgrade` (D90) runs with SQLite's
    default `foreign_keys=OFF`, so the rebuild that drops the referencing columns keeps every project and item."""
    with op.batch_alter_table("projects") as batch:
        for column in _ANCHOR_COLUMNS:
            batch.drop_column(column)

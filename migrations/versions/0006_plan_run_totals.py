"""plan run totals

Slice 02's one revision, so the Pi migrates once: `totals` (filled now), `report` (05-08), `fingerprint` and
`memo_hit` (05-10). Runs stored before it keep no totals; they are not recomputed.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NULLABLE_COLUMNS = (("totals", sa.JSON()), ("report", sa.JSON()), ("fingerprint", sa.Text()))


def upgrade() -> None:
    """Added in place (`ADD COLUMN`), so `plan_runs` is not rebuilt and every stored run stays (brief §9)."""
    for name, type_ in _NULLABLE_COLUMNS:
        op.add_column("plan_runs", sa.Column(name, type_, nullable=True))
    op.add_column("plan_runs", sa.Column("memo_hit", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Every revision has a CI-tested downgrade (DV-5). SQLite drops the columns by rebuilding `plan_runs` (batch mode);
    nothing references `plan_runs`, so the rebuild cascades nowhere, even with foreign keys on, and every run stays.
    """
    with op.batch_alter_table("plan_runs") as batch:
        for name in ("memo_hit", *(name for name, _ in _NULLABLE_COLUMNS)):
            batch.drop_column(name)

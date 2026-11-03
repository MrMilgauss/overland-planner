"""project anchors

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import cast

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
    """Every revision has a CI-tested downgrade (DV-5). Dropping a referencing column rebuilds `projects`, and the
    rebuild's DROP TABLE would cascade-delete every item while foreign keys are enforced (the planner's connections
    run `foreign_keys=ON`). So enforcement is switched off around the rebuild and restored after it. SQLite ignores
    `PRAGMA foreign_keys` inside a transaction, so an open one (earlier steps of this run) is committed first."""
    with _foreign_keys_off(), op.batch_alter_table("projects") as batch:
        for column in _ANCHOR_COLUMNS:
            batch.drop_column(column)


@contextmanager
def _foreign_keys_off() -> Iterator[None]:
    if op.get_context().as_sql:
        op.execute("PRAGMA foreign_keys=OFF")
        yield
        op.execute("PRAGMA foreign_keys=ON")
        return
    driver = cast(sqlite3.Connection, op.get_bind().connection.driver_connection)
    enforced = bool(driver.execute("PRAGMA foreign_keys").fetchone()[0])
    if not enforced:
        yield
        return
    _outside_a_transaction(driver, "PRAGMA foreign_keys=OFF")
    try:
        yield
    finally:
        _outside_a_transaction(driver, "PRAGMA foreign_keys=ON")


def _outside_a_transaction(driver: sqlite3.Connection, pragma: str) -> None:
    if driver.in_transaction:
        driver.commit()
    driver.execute(pragma).close()

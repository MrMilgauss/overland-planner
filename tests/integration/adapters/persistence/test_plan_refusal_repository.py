"""`plan_refusals` on SQLite (ADR-013 Amendment 4, D248): the row every refused plan request leaves, and its probe.

Integration level: single examples on a real SQLite file at head in a workspace data folder; they verify the wiring.
Test Budget: 3 behaviors (append-only rows with the clock's time, the probe's round trip, a table that cannot be
written) x 2 = 6; 3 used.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.migrator import AlembicMigrator, DatabaseStartup
from overland_planner.adapters.persistence.plan_refusal_repository import SqlAlchemyPlanRefusalLog
from overland_planner.application.ports.probe import ProbeResult
from tests.common.fakes import FakeClock
from tests.common.workspace import workspace_data_dir

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 11, 9, 7, 0, tzinfo=UTC)


@pytest.fixture
def database() -> Iterator[SqliteDatabase]:
    with workspace_data_dir("integration") as data_dir:
        database = SqliteDatabase(data_dir)
        assert DatabaseStartup(database, AlembicMigrator(database, REPO_ROOT / "migrations"), FakeClock()).probe() == (
            ProbeResult(outcome="ok")
        )
        try:
            yield database
        finally:
            database.engine.dispose()


def _rows(database: SqliteDatabase) -> list[dict[str, Any]]:
    with sqlite3.connect(database.file) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute("SELECT * FROM plan_refusals ORDER BY id")]
    connection.close()
    return rows


def test_every_refusal_appends_a_row_with_the_clocks_time_and_none_is_ever_replaced(database: SqliteDatabase) -> None:
    clock = FakeClock(NOW)
    log = SqlAlchemyPlanRefusalLog(database, clock)

    log.append("p1", "routing_engine_not_ready", 503)
    clock.advance(300)
    log.append("p1", "routing_engine_not_ready", 503)
    log.append("p2", "missing_anchor", 422)

    rows = _rows(database)
    assert [(row["project_id"], row["reason"], row["http_status"]) for row in rows] == [
        ("p1", "routing_engine_not_ready", 503),
        ("p1", "routing_engine_not_ready", 503),
        ("p2", "missing_anchor", 422),
    ]
    assert [row["created_at"] for row in rows] == ["2026-11-09 07:00:00.000000"] + ["2026-11-09 07:05:00.000000"] * 2
    assert len({row["id"] for row in rows}) == 3


def test_the_probe_writes_and_reads_a_row_and_leaves_none(database: SqliteDatabase) -> None:
    log = SqlAlchemyPlanRefusalLog(database, FakeClock(NOW))

    assert log.probe() == ProbeResult(outcome="ok")

    assert _rows(database) == []
    assert database.writer_lock.acquire(blocking=False), "the probe left the writer lock held"
    database.writer_lock.release()


def test_a_table_that_cannot_be_written_fails_the_probe_and_the_append(database: SqliteDatabase) -> None:
    with sqlite3.connect(database.file) as connection:
        connection.execute("DROP TABLE plan_refusals")
    connection.close()
    log = SqlAlchemyPlanRefusalLog(database, FakeClock(NOW))

    assert log.probe() == ProbeResult(outcome="fatal", reason="plan_refusal_log_unwritable")
    with pytest.raises(SQLAlchemyError):
        log.append("p1", "job_active", 409)
    assert database.writer_lock.acquire(blocking=False), "a failed write left the writer lock held"
    database.writer_lock.release()

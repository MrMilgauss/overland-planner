"""`plan_job_log` on SQLite (ADR-015 DV-2, ADR-018): the row a job writes, its probe, and a write that cannot land.

Integration level: single examples on a real SQLite file at head in a workspace data folder; they verify the wiring.
The invariants (one row per ending, the line's values, nothing else changed) live in tests/unit/application/planning.
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
from overland_planner.adapters.persistence.plan_job_log_repository import SqlAlchemyPlanJobLog
from overland_planner.application.ports.plan_job_log import PlanJobLogEntry
from overland_planner.application.ports.probe import ProbeResult
from tests.common.fakes import FakeClock
from tests.common.workspace import workspace_data_dir

REPO_ROOT = Path(__file__).resolve().parents[4]
STARTED = datetime(2026, 11, 9, 7, 0, tzinfo=UTC)
ENDED = datetime(2026, 11, 9, 7, 0, 42, tzinfo=UTC)
LINE = {  # a solved job's plan.job.finished fields; exit_code and signal are line-only
    "job_id": "j1",
    "project_id": "p1",
    "terminal_state": "done",
    "plan_run_id": "r1",
    "items_included": 7,
    "legs_total": 42,
    "memo_hit": False,
    "ignore_memo": True,
    "stage_ms": {"snapshot": 3, "matrix": 120, "reach_model": 1, "solve": 41000, "guard_persist": 9},
    "provider_id": "mock",
    "elapsed_ms": 41200,
    "reason": None,
    "points_located": None,
}


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


def _rows(database: SqliteDatabase, table: str) -> list[dict[str, Any]]:
    with sqlite3.connect(database.file) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]  # noqa: S608 - fixed names
    connection.close()
    return rows


def test_a_job_row_is_written_with_the_line_values_and_the_app_version(database: SqliteDatabase) -> None:
    log = SqlAlchemyPlanJobLog(database, app_version="0123456789ab")

    log.append(PlanJobLogEntry(STARTED, ENDED, LINE))

    (row,) = _rows(database, "plan_job_log")
    assert {name: row[name] for name in ("job_id", "project_id", "terminal_state", "plan_run_id")} == {
        "job_id": "j1",
        "project_id": "p1",
        "terminal_state": "done",
        "plan_run_id": "r1",
    }
    assert (row["items_included"], row["legs_total"], row["elapsed_ms"], row["provider_id"]) == (7, 42, 41200, "mock")
    assert (row["memo_hit"], row["ignore_memo"], row["app_version"]) == (0, 1, "0123456789ab")
    assert row["stage_ms"] == '{"snapshot": 3, "matrix": 120, "reach_model": 1, "solve": 41000, "guard_persist": 9}'
    assert (row["started_at"], row["ended_at"]) == ("2026-11-09 07:00:00.000000", "2026-11-09 07:00:42.000000")
    later = ("legs_new", "solver_solutions", "reproducible", "solver_wait_s", "error_class", "reason", "retraces")
    assert all(row[name] is None for name in later)
    assert "exit_code" not in row and "points_located" not in row
    assert _rows(database, "plan_runs") == [] and _rows(database, "projects") == []


def test_the_probe_writes_and_reads_a_row_and_leaves_none(database: SqliteDatabase) -> None:
    log = SqlAlchemyPlanJobLog(database, app_version="dev")

    assert log.probe() == ProbeResult(outcome="ok")

    assert _rows(database, "plan_job_log") == []
    assert database.writer_lock.acquire(blocking=False), "the probe left the writer lock held"
    database.writer_lock.release()


def test_a_table_that_cannot_be_written_fails_the_probe_and_the_append(database: SqliteDatabase) -> None:
    with sqlite3.connect(database.file) as connection:
        connection.execute("DROP TABLE plan_job_log")
    connection.close()
    log = SqlAlchemyPlanJobLog(database, app_version="dev")

    assert log.probe() == ProbeResult(outcome="fatal", reason="plan_job_log_unwritable")
    with pytest.raises(SQLAlchemyError):
        log.append(PlanJobLogEntry(STARTED, ENDED, LINE))
    assert database.writer_lock.acquire(blocking=False), "a failed write left the writer lock held"
    database.writer_lock.release()

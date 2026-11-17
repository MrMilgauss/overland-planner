"""`DiagnosticsReader` on SQLite (DV-3, kpi-contracts `diagnostics_endpoint`): the rows behind the diagnostics.

Integration level: single examples on a real SQLite file at head; they verify the wiring (the window bound, the
project's name, the JSON columns, a read beside a held writer lock, nothing written). The arithmetic lives in
tests/unit/application/platform/test_diagnostics_service.py.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert

from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.diagnostics_reader import SqlAlchemyDiagnosticsReader
from overland_planner.adapters.persistence.migrator import AlembicMigrator, DatabaseStartup
from overland_planner.adapters.persistence.plan_job_log_repository import SqlAlchemyPlanJobLog
from overland_planner.adapters.persistence.plan_refusal_repository import SqlAlchemyPlanRefusalLog
from overland_planner.adapters.persistence.tables import plan_runs, projects
from overland_planner.application.ports.diagnostics_reader import JobLogRow, PlanRunRow, RefusalRow
from overland_planner.application.ports.plan_job_log import PlanJobLogEntry
from overland_planner.application.ports.probe import ProbeResult
from tests.common.fakes import FakeClock
from tests.common.workspace import workspace_data_dir

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 11, 9, 19, 0, tzinfo=UTC)
STAGES = {"snapshot": 3, "matrix": 120, "reach_model": 1, "solve": 41000, "guard_persist": 9}


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


def _job(job_id: str, project_id: str, started: datetime, **fields: Any) -> PlanJobLogEntry:
    line = {"job_id": job_id, "project_id": project_id, "memo_hit": False, "ignore_memo": False, **fields}
    return PlanJobLogEntry(started, started + timedelta(seconds=42), line)


def _seed(database: SqliteDatabase) -> None:
    with database.engine.begin() as connection:
        connection.execute(
            insert(projects).values(
                id="p1", name="Alpi Occidentali", objective="min_time", settings={}, revision=3, created_at=NOW
            )
        )
        connection.execute(
            insert(plan_runs).values(
                id="r1",
                project_id="p1",
                number=1,
                status="ready",
                created_at=NOW - timedelta(hours=1),
                revision=3,
                provider_id="mock",
                objective="min_time",
                inputs={"start_item_id": "a", "end_item_id": "a", "included_item_ids": ["a", "b"]},
                itinerary={"stops": [{"item_id": "a"}, {"item_id": "b"}, {"item_id": "a"}]},
            )
        )
    log = SqlAlchemyPlanJobLog(database, app_version="dev")
    done = {"terminal_state": "done", "items_included": 60, "stage_ms": STAGES, "elapsed_ms": 41200, "retried": True}
    log.append(_job("j1", "p1", NOW - timedelta(hours=2), **done, second_pass_pairs=720))
    log.append(_job("j2", "gone", NOW - timedelta(days=2), terminal_state="failed", elapsed_ms=900))
    log.append(_job("j3", "p1", NOW - timedelta(days=40), terminal_state="done", elapsed_ms=5))
    clock = FakeClock(NOW - timedelta(days=40))
    refusals = SqlAlchemyPlanRefusalLog(database, clock)
    refusals.append("p1", "routing_engine_unreachable", 503)  # outside the 30 days
    clock.advance(38 * 24 * 3600)
    refusals.append("gone", "routing_engine_not_ready", 503)


def _tables(database: SqliteDatabase) -> dict[str, list[tuple[Any, ...]]]:
    with sqlite3.connect(database.file) as connection:
        tables = {
            name: connection.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()  # noqa: S608 - fixed names
            for name in ("plan_job_log", "plan_refusals", "plan_runs", "projects")
        }
    connection.close()
    return tables


def test_the_window_rows_are_read_with_the_project_name_while_a_writer_holds_the_lock(
    database: SqliteDatabase,
) -> None:
    _seed(database)
    reader = SqlAlchemyDiagnosticsReader(database)
    stored = _tables(database)
    answers: dict[str, Any] = {}

    def read() -> None:
        answers["jobs"] = reader.jobs_since(NOW - timedelta(days=30))
        answers["runs"] = reader.plan_runs()
        answers["refusals"] = reader.refusals_since(NOW - timedelta(days=30))
        answers["exists"] = (reader.project_exists("p1"), reader.project_exists("gone"))

    with database.writer_lock:
        reading = threading.Thread(target=read)
        reading.start()
        reading.join(timeout=10)
        assert not reading.is_alive(), "the read waited for the writer lock"

    assert sorted(answers["jobs"], key=lambda job: job.project_id) == [
        JobLogRow("gone", None, NOW - timedelta(days=2), "failed", 900, False),
        JobLogRow(
            "p1",
            "Alpi Occidentali",
            NOW - timedelta(hours=2),
            "done",
            41200,
            False,
            items_included=60,
            stage_ms=STAGES,
            retried=True,
            second_pass_pairs=720,
        ),
    ]
    assert answers["runs"] == [
        PlanRunRow("p1", NOW - timedelta(hours=1), "ready", None, ("a", "b"), ("a", "b", "a")),
    ]
    assert answers["refusals"] == [RefusalRow("gone", "routing_engine_not_ready", NOW - timedelta(days=2))]
    assert answers["exists"] == (True, False)
    assert _tables(database) == stored


def test_the_probe_reads_an_empty_window_and_writes_nothing(database: SqliteDatabase) -> None:
    _seed(database)
    stored = _tables(database)

    assert SqlAlchemyDiagnosticsReader(database).probe() == ProbeResult(outcome="ok")

    assert _tables(database) == stored

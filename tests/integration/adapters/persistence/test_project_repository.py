"""`projects` on SQLite (slice 06a, D249): the objective column of a project row.

Integration level: single examples on a real SQLite file at head in a workspace data folder; they verify the wiring.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert

from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.migrator import AlembicMigrator, DatabaseStartup
from overland_planner.adapters.persistence.project_repository import SqlAlchemyProjectRepository
from overland_planner.adapters.persistence.tables import projects
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.domain.catalog.project import Objective
from tests.common.fakes import FakeClock
from tests.common.workspace import workspace_data_dir

REPO_ROOT = Path(__file__).resolve().parents[4]
CREATED = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)


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


class _Silent:
    def warning(self, event: str, **fields: object) -> None: ...


@pytest.mark.parametrize(
    ("stored", "read"),
    [("distance", Objective.DISTANCE), ("time", Objective.TIME), ("min_time", Objective.DISTANCE)],
    ids=["written before this step", "time", "a value no code writes"],
)
def test_a_project_row_reads_its_objective_and_an_old_row_reads_distance(
    database: SqliteDatabase, stored: str, read: Objective
) -> None:
    # bypass: three stored values of one column; the row has no objective key in `settings`, as before this step.
    with database.engine.begin() as connection:
        connection.execute(
            insert(projects).values(id="p1", name="Trip", objective=stored, settings={}, revision=1, created_at=CREATED)
        )
        project = SqlAlchemyProjectRepository(connection, _Silent()).get("p1")  # type: ignore[arg-type]

    assert project is not None
    assert project.objective is read


def test_an_updated_objective_is_stored_in_the_column(database: SqliteDatabase) -> None:
    with database.engine.begin() as connection:
        repository = SqlAlchemyProjectRepository(connection, _Silent())  # type: ignore[arg-type]
        connection.execute(
            insert(projects).values(
                id="p1", name="Trip", objective="distance", settings={}, revision=1, created_at=CREATED
            )
        )
        project = repository.get("p1")
        assert project is not None
        repository.update(project.with_settings(Objective.TIME, None))
        stored = connection.exec_driver_sql("SELECT objective, revision FROM projects").fetchall()

    assert stored == [("time", 2)]

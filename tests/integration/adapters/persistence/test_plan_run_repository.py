"""`plan_runs` itinerary on SQLite (brief section 9, ADR-017 section 3): a plan with a retrace reads back as stored, and
a run stored before the levels and the retrace reads back with every new field null, no migration.

Integration level: single examples on a real SQLite file at head in a workspace data folder; they verify the wiring.
The assembly itself lives in tests/unit/domain/planning.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert, update

from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.migrator import AlembicMigrator, DatabaseStartup
from overland_planner.adapters.persistence.plan_run_repository import SqlAlchemyPlanRunRepository
from overland_planner.adapters.persistence.tables import plan_runs, projects
from overland_planner.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from overland_planner.application.ports.plan_run_repository import NewPlanRun
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.planning.plan_run import RETRACE_REASON, PlanStop, Totals
from tests.common.fakes import FakeClock
from tests.common.workspace import workspace_data_dir

REPO_ROOT = Path(__file__).resolve().parents[4]
CREATED = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
HOME, ENTRY, EXIT = Coordinate(45.0, 7.0), Coordinate(45.1, 7.1), Coordinate(45.2, 7.2)
NEW_FIELDS = ("confidence", "reason", "leg_confidence", "leg_reason", "retrace_sha256")


@pytest.fixture
def database() -> Iterator[SqliteDatabase]:
    with workspace_data_dir("integration") as data_dir:
        database = SqliteDatabase(data_dir)
        assert DatabaseStartup(database, AlembicMigrator(database, REPO_ROOT / "migrations"), FakeClock()).probe() == (
            ProbeResult(outcome="ok")
        )
        with database.engine.begin() as connection:
            connection.execute(
                insert(projects).values(
                    id="p1", name="Trip", objective="min_time", settings={}, revision=1, created_at=CREATED
                )
            )
        try:
            yield database
        finally:
            database.engine.dispose()


def _stops() -> tuple[PlanStop, ...]:
    home = PlanStop(item_id="home", name="Casa", kind="poi", leg_km=None, location=HOME, cumulative_km=0.0)
    track = PlanStop(
        item_id="t1",
        name="Sommeiller",
        kind="track",
        leg_km=58.0,
        entry=ENTRY,
        exit=EXIT,
        leg_s=3480,
        track_km=12.4,
        offroad_s=2976.0,
        cumulative_km=70.4,
        cumulative_s=6456.0,
        direction_version=1,
        point_count=25,
        canonical_sha256="abc",
        leg_confidence="confirmed",
    )
    retrace = PlanStop(
        item_id="t1",
        name="Retrace Sommeiller",
        kind="retrace",
        leg_km=None,
        entry=EXIT,
        exit=ENTRY,
        track_km=12.4,
        offroad_s=2976.0,
        cumulative_km=82.8,
        cumulative_s=9432.0,
        confidence="unconfirmed",
        reason=RETRACE_REASON,
    )
    back = PlanStop(
        item_id="home",
        name="Casa",
        kind="poi",
        leg_km=64.0,
        location=HOME,
        leg_s=3840,
        cumulative_km=146.8,
        cumulative_s=13272.0,
        leg_confidence="unconfirmed",
        leg_reason="exit is 1.2 km from the nearest road - check on the ground",
    )
    return home, track, retrace, back


def _run(stops: tuple[PlanStop, ...], profile: str | None = "4x4.v1") -> NewPlanRun:
    return NewPlanRun(
        id="r1",
        project_id="p1",
        number=1,
        status="ready",
        failure_reason=None,
        created_at=CREATED,
        revision=1,
        provider_id="mock",
        profile=profile,
        objective="min_time",
        inputs={"included_item_ids": ["t1"]},
        stops=stops,
        totals=Totals.of(stops),
    )


def test_a_plan_with_a_retrace_and_leg_levels_reads_back_as_stored(database: SqliteDatabase) -> None:
    stops = _stops()
    with SqlAlchemyUnitOfWork(database) as work:
        SqlAlchemyPlanRunRepository(work.connection).add(_run(stops))
        work.commit()

    with SqlAlchemyUnitOfWork(database) as work:
        stored = SqlAlchemyPlanRunRepository(work.connection).get("r1")

    assert stored is not None
    assert stored.stops == stops
    assert stored.totals == Totals.of(stops)


def test_a_run_stored_before_the_levels_and_the_retrace_reads_back_with_them_null(database: SqliteDatabase) -> None:
    old_stop = {
        "item_id": "t1",
        "name": "Sommeiller",
        "kind": "track",
        "leg_km": 58.0,
        "location": None,
        "entry": {"lat": 45.1, "lon": 7.1},
        "exit": {"lat": 45.2, "lon": 7.2},
        "direction_version": 1,
        "point_count": 25,
        "canonical_sha256": "abc",
        "leg_s": 3480,
        "track_km": 12.4,
        "offroad_s": 2976.0,
        "cumulative_km": 70.4,
        "cumulative_s": 6456.0,
    }
    with SqlAlchemyUnitOfWork(database) as work:
        SqlAlchemyPlanRunRepository(work.connection).add(_run(_stops()))
        # SQL-level: the itinerary and report as a run stored before this step wrote them (no new keys, no `items`)
        work.connection.execute(
            update(plan_runs)
            .where(plan_runs.c.id == "r1")
            .values(itinerary={"stops": [old_stop]}, report={"reason": "unreachable"})
        )
        work.commit()

    with SqlAlchemyUnitOfWork(database) as work:
        stored = SqlAlchemyPlanRunRepository(work.connection).get("r1")

    assert stored is not None
    assert [(stop.item_id, stop.kind, stop.track_km) for stop in stored.stops] == [("t1", "track", 12.4)]
    assert [getattr(stored.stops[0], name) for name in NEW_FIELDS] == [None] * len(NEW_FIELDS)
    assert stored.report is not None
    assert stored.report.items == ()


def test_a_run_reads_back_the_road_map_and_profile_it_stored_and_one_stored_before_has_no_profile(
    database: SqliteDatabase,
) -> None:
    with SqlAlchemyUnitOfWork(database) as work:
        repository = SqlAlchemyPlanRunRepository(work.connection)
        repository.add(_run(_stops()))
        repository.add(replace(_run(_stops(), profile=None), id="r0", number=2))
        work.commit()

    with SqlAlchemyUnitOfWork(database) as work:
        repository = SqlAlchemyPlanRunRepository(work.connection)
        stored, before = repository.get("r1"), repository.get("r0")

    assert stored is not None and before is not None
    assert [(run.provider_id, run.profile) for run in (stored, before)] == [("mock", "4x4.v1"), ("mock", None)]

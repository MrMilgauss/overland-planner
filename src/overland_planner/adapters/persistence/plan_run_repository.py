"""`PlanRunRepository` on SQLAlchemy Core, bound to the connection of one `SqlAlchemyUnitOfWork`.

The itinerary JSON holds everything a `PlanStop` holds; HTTP shows a subset. A Failed run has no itinerary and no
totals (SQL NULL), nor has a run stored before 0006. A stop stored before its driving columns were (05-07) reads them
as `None`: runs are not recomputed. `report` holds a Failed run's reason in product words; a ready run, and any run
stored before 05-08, has none (SQL NULL). `fingerprint` and `memo_hit` (05-10) are stored on every run; a run stored
before has a null fingerprint and is never a memo source.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any

from sqlalchemy import Connection, RowMapping, func, null, select

from overland_planner.adapters.persistence.tables import plan_runs
from overland_planner.application.ports.plan_run_repository import NewPlanRun, PlanRunDetail
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.planning.plan_run import PlanRun, PlanStop, Totals
from overland_planner.domain.planning.plan_run_assembler import PlanReport

_STOP_FIELDS = tuple(field.name for field in fields(PlanStop))
_POINT_FIELDS = frozenset({"location", "entry", "exit"})
_DRIVING_FIELDS = frozenset({"leg_s", "track_km", "offroad_s", "cumulative_km", "cumulative_s"})


class SqlAlchemyPlanRunRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def list(self, project_id: str) -> list[PlanRun]:
        query = (
            select(plan_runs.c.id, plan_runs.c.number, plan_runs.c.status, plan_runs.c.revision)
            .where(plan_runs.c.project_id == project_id)
            .order_by(plan_runs.c.number)
        )
        rows = self._connection.execute(query).mappings()
        return [
            PlanRun(id=row["id"], number=row["number"], status=row["status"], revision=row["revision"]) for row in rows
        ]

    def get(self, plan_run_id: str) -> PlanRunDetail | None:
        query = select(plan_runs).where(plan_runs.c.id == plan_run_id)
        return _detail(self._connection.execute(query).mappings().first())

    def latest_ready(self, project_id: str, fingerprint: str) -> PlanRunDetail | None:
        query = (
            select(plan_runs)
            .where(
                plan_runs.c.project_id == project_id,
                plan_runs.c.fingerprint == fingerprint,
                plan_runs.c.status == "ready",
            )
            .order_by(plan_runs.c.number.desc())
            .limit(1)
        )
        return _detail(self._connection.execute(query).mappings().first())

    def next_number(self, project_id: str) -> int:
        query = select(func.max(plan_runs.c.number)).where(plan_runs.c.project_id == project_id)
        return (self._connection.execute(query).scalar_one() or 0) + 1

    def add(self, run: NewPlanRun) -> None:
        self._connection.execute(
            plan_runs.insert().values(
                id=run.id,
                project_id=run.project_id,
                number=run.number,
                status=run.status,
                failure_reason=run.failure_reason,
                created_at=run.created_at,
                revision=run.revision,
                provider_id=run.provider_id,
                objective=run.objective,
                inputs=dict(run.inputs),
                itinerary={"stops": [_stop_json(stop) for stop in run.stops]} if run.stops else null(),
                totals=null() if run.totals is None else asdict(run.totals),
                report=null() if run.report is None else asdict(run.report),
                fingerprint=run.fingerprint,
                memo_hit=run.memo_hit,
            )
        )


def _detail(row: RowMapping | None) -> PlanRunDetail | None:
    if row is None:
        return None
    return PlanRunDetail(
        id=row["id"],
        project_id=row["project_id"],
        number=row["number"],
        status=row["status"],
        failure_reason=row["failure_reason"],
        stops=_stops(row["itinerary"]),
        totals=None if row["totals"] is None else Totals(**row["totals"]),
        report=None if row["report"] is None else PlanReport(reason=row["report"]["reason"]),
    )


def _stop_json(stop: PlanStop) -> dict[str, Any]:
    """Every field of the stop under its own name, in field order; points as {lat, lon}."""
    values = {name: getattr(stop, name) for name in _STOP_FIELDS}
    return {name: _point_json(value) if name in _POINT_FIELDS else value for name, value in values.items()}


def _point_json(point: Coordinate | None) -> dict[str, float] | None:
    return None if point is None else {"lat": point.latitude, "lon": point.longitude}


def _stops(itinerary: dict[str, Any] | None) -> tuple[PlanStop, ...]:
    return () if itinerary is None else tuple(_stop(stop) for stop in itinerary["stops"])


def _stop(stored: dict[str, Any]) -> PlanStop:
    """A stop stored before the driving fields (05-07) reads them as `None`; every other field must be there."""
    values = {name: stored.get(name) if name in _DRIVING_FIELDS else stored[name] for name in _STOP_FIELDS}
    read: dict[str, Any] = {name: _point(value) if name in _POINT_FIELDS else value for name, value in values.items()}
    return PlanStop(**read)


def _point(point: dict[str, float] | None) -> Coordinate | None:
    return None if point is None else Coordinate(point["lat"], point["lon"])

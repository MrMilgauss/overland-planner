"""In-memory doubles of planning's driven ports for unit tests (they honour the production Protocols and preconditions).

`InMemoryPlanning` stands for the database: a unit of work holds the one writer lock and stages its changes, and only
`commit()` publishes them. `InMemoryPlanJobLog` stands for the `plan_job_log` table of the same database: it writes
under that writer lock, can be made to fail like a full disk, and refuses a row naming a run that is not stored.
`RecordingRoadMap` answers from a table of road legs and refuses identical points, which no
router answers. A `Gate` holds a double at one point of the job until the test releases it; a `Taking` gate also
moves a `FakeClock` on by its duration at every passing after the first `free` ones.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from overland_planner.application.planning.facade import PlanJobRegistry, PlanJobView
from overland_planner.application.ports.plan_job_log import PlanJobLogEntry
from overland_planner.application.ports.plan_run_repository import NewPlanRun, PlanRunDetail
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.project_snapshot_reader import ProjectStamp
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.planning.plan_run import PlanRun, PlanRunStatus
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.routing.road_leg import RoadMeasure
from tests.common.fakes import FakeClock

MAX_WAIT_S = 30.0
POLL_S = 0.0005
DEFAULT_STAMP = ProjectStamp(revision=3, objective="distance")
TERMINAL_STATES = {"done", "failed", "refused", "cancelled", "timed_out"}


def known_job(registry: PlanJobRegistry, job_id: str) -> PlanJobView:
    job = registry.get(job_id)
    assert job is not None, f"job {job_id} is not known"
    return job


def job_when_ended(registry: PlanJobRegistry, job_id: str) -> PlanJobView:
    deadline = time.monotonic() + MAX_WAIT_S
    job = known_job(registry, job_id)
    while job.state not in TERMINAL_STATES:
        assert time.monotonic() < deadline, f"the job did not end: {job}"
        time.sleep(POLL_S)
        job = known_job(registry, job_id)
    return job


class Gate:
    """Open by default. A held gate blocks whoever passes until `release`; `reached` tells that somebody came."""

    def __init__(self, *, held: bool = False) -> None:
        self.reached = threading.Event()
        self._open = threading.Event()
        if not held:
            self._open.set()

    def passing(self) -> None:
        self.reached.set()
        assert self._open.wait(MAX_WAIT_S), "the test never released this gate"

    def release(self) -> None:
        self._open.set()


class Taking(Gate):
    """A gate whose passings take `seconds` on the clock, but the first `free`; `passings` counts those that took."""

    def __init__(self, clock: FakeClock, seconds: float, *, free: int = 0, held: bool = False) -> None:
        super().__init__(held=held)
        self._clock = clock
        self._seconds = seconds
        self._free = free
        self.passings = 0

    def passing(self) -> None:
        super().passing()
        if self._free > 0:
            self._free -= 1
            return
        self.passings += 1
        self._clock.advance(self._seconds)


@dataclass
class InMemoryPlanning:
    snapshots: dict[str, ProjectSnapshot] = field(default_factory=dict)
    stamps: dict[str, ProjectStamp] = field(default_factory=dict)
    runs: list[NewPlanRun] = field(default_factory=list)
    commits: int = 0
    reading: Gate = field(default_factory=Gate)
    storing: Gate = field(default_factory=Gate)
    writer_lock: threading.Lock = field(default_factory=threading.Lock)

    def unit_of_work(self) -> InMemoryPlanningUnitOfWork:
        return InMemoryPlanningUnitOfWork(self)

    def add_project(self, project_id: str, snapshot: ProjectSnapshot, stamp: ProjectStamp = DEFAULT_STAMP) -> None:
        self.snapshots[project_id] = snapshot
        self.stamps[project_id] = stamp

    def seed_run(self, project_id: str, number: int, status: PlanRunStatus = "ready", revision: int = 1) -> None:
        self.runs.append(
            NewPlanRun(
                id=f"{project_id}-seeded-{number}",
                project_id=project_id,
                number=number,
                status=status,
                failure_reason=None,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                revision=revision,
                provider_id="seeded",
                objective="distance",
                inputs={},
                stops=(),
            )
        )


@dataclass
class InMemoryPlanJobLog:
    planning: InMemoryPlanning
    rows: list[PlanJobLogEntry] = field(default_factory=list)
    failing: Exception | None = None

    def append(self, entry: PlanJobLogEntry) -> None:
        assert self.planning.writer_lock.acquire(timeout=MAX_WAIT_S), "another unit of work kept the writer lock"
        try:
            if self.failing is not None:
                raise self.failing
            run_id = entry.fields.get("plan_run_id")
            assert run_id is None or any(run.id == run_id for run in self.planning.runs), "the row names no stored run"
            self.rows.append(entry)
        finally:
            self.planning.writer_lock.release()

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


class _Runs:
    def __init__(self, rows: list[NewPlanRun], gate: Gate) -> None:
        self._rows = rows
        self._gate = gate

    def list(self, project_id: str) -> list[PlanRun]:
        rows = sorted((row for row in self._rows if row.project_id == project_id), key=lambda row: row.number)
        return [
            PlanRun(
                id=row.id,
                number=row.number,
                status=row.status,
                revision=row.revision,
                reproducible=row.reproducible,
                not_fully_optimised=row.not_fully_optimised,
            )
            for row in rows
        ]

    def get(self, plan_run_id: str) -> PlanRunDetail | None:
        for row in self._rows:
            if row.id == plan_run_id:
                return PlanRunDetail(
                    row.id,
                    row.project_id,
                    row.number,
                    row.status,
                    row.failure_reason,
                    row.stops,
                    row.totals,
                    row.report,
                    reproducible=row.reproducible,
                    not_fully_optimised=row.not_fully_optimised,
                    memo_hit=row.memo_hit,
                    run_time_ms=row.run_time_ms,
                    memo_source_run_id=row.memo_source_run_id,
                    items_planned=_items_planned(row.inputs),
                )
        return None

    def latest_ready(self, project_id: str, fingerprint: str) -> PlanRunDetail | None:
        sources = [
            row
            for row in self._rows
            if (row.project_id, row.status, row.fingerprint) == (project_id, "ready", fingerprint)
        ]
        return None if not sources else self.get(max(sources, key=lambda row: row.number).id)

    def next_number(self, project_id: str) -> int:
        return max((row.number for row in self._rows if row.project_id == project_id), default=0) + 1

    def add(self, run: NewPlanRun) -> None:
        self._gate.passing()
        taken = {(row.project_id, row.number) for row in self._rows}
        assert (run.project_id, run.number) not in taken, "UNIQUE constraint failed: plan_runs.project_id, number"
        assert run.number >= 1, "plan runs are numbered from 1"
        assert run.provider_id, "plan_runs.provider_id is NOT NULL"
        assert run.objective, "plan_runs.objective is NOT NULL"
        self._rows.append(replace(run))


def _items_planned(inputs: Mapping[str, object]) -> int | None:
    included = inputs.get("included_item_ids")
    return len(included) if isinstance(included, list | tuple) else None


class _Snapshots:
    def __init__(self, planning: InMemoryPlanning) -> None:
        self._planning = planning

    def read(self, project_id: str) -> ProjectSnapshot | None:
        self._planning.reading.passing()
        return self._planning.snapshots.get(project_id)

    def stamp(self, project_id: str) -> ProjectStamp:
        return self._planning.stamps[project_id]


class InMemoryPlanningUnitOfWork:
    def __init__(self, planning: InMemoryPlanning) -> None:
        self._planning = planning
        self._staged: list[NewPlanRun] = []
        self.plan_runs = _Runs(self._staged, planning.storing)
        self.project_snapshots = _Snapshots(planning)

    def __enter__(self) -> Self:
        assert self._planning.writer_lock.acquire(timeout=MAX_WAIT_S), "another unit of work kept the writer lock"
        self._staged.extend(self._planning.runs)
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._planning.writer_lock.release()

    def commit(self) -> None:
        self._planning.runs = list(self._staged)
        self._planning.commits += 1


class RecordingRoadMap:
    """Road legs from a table; `asked` counts every pair the road map was asked for.

    The road time of a leg is `leg_s[pair]` when given, else the distance driven at about 60 km/h (at least 1 s).
    """

    provider_id = "road-map-double"

    def __init__(
        self,
        leg_m: Mapping[tuple[Coordinate, Coordinate], int],
        *,
        leg_s: Mapping[tuple[Coordinate, Coordinate], int] | None = None,
        gate: Gate | None = None,
    ) -> None:
        self._leg_m = leg_m
        self._leg_s = leg_s
        self.gate = gate or Gate()
        self.asked: Counter[tuple[Coordinate, Coordinate]] = Counter()

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def matrix(self, sources: Sequence[Coordinate], targets: Sequence[Coordinate]) -> Sequence[Sequence[RoadMeasure]]:
        self.gate.passing()
        self.asked.update((source, target) for source in sources for target in targets)
        return [[self._measure(source, target) for target in targets] for source in sources]

    def _measure(self, source: Coordinate, target: Coordinate) -> RoadMeasure:
        metres = self._leg_m[source, target]
        seconds = max(1, metres * 3 // 50) if self._leg_s is None else self._leg_s[source, target]
        return RoadMeasure(metres, seconds)

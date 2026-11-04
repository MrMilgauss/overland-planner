"""In-memory doubles of planning's driven ports for unit tests (they honour the production Protocols and preconditions).

`InMemoryPlanning` stands for the database: a unit of work holds the one writer lock and stages its changes, and only
`commit()` publishes them. `RecordingRoadMap` answers from a table of road legs and refuses identical points, which no
router answers. A `Gate` holds a double at one point of the job until the test releases it.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from overland_planner.application.ports.plan_run_repository import NewPlanRun, PlanRunDetail
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.project_snapshot_reader import ProjectStamp
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.planning.plan_run import PlanRun, PlanRunStatus
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot

MAX_WAIT_S = 30.0
DEFAULT_STAMP = ProjectStamp(revision=3, objective="distance")


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

    def seed_run(self, project_id: str, number: int, status: PlanRunStatus = "ready") -> None:
        self.runs.append(
            NewPlanRun(
                id=f"{project_id}-seeded-{number}",
                project_id=project_id,
                number=number,
                status=status,
                failure_reason=None,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                revision=1,
                provider_id="seeded",
                objective="distance",
                inputs={},
                stops=(),
            )
        )


class _Runs:
    def __init__(self, rows: list[NewPlanRun], gate: Gate) -> None:
        self._rows = rows
        self._gate = gate

    def list(self, project_id: str) -> list[PlanRun]:
        rows = sorted((row for row in self._rows if row.project_id == project_id), key=lambda row: row.number)
        return [PlanRun(id=row.id, number=row.number, status=row.status) for row in rows]

    def get(self, plan_run_id: str) -> PlanRunDetail | None:
        for row in self._rows:
            if row.id == plan_run_id:
                return PlanRunDetail(row.id, row.project_id, row.number, row.status, row.failure_reason, row.stops)
        return None

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
    """Road legs from a table; `asked` counts every pair the road map was asked for."""

    provider_id = "road-map-double"

    def __init__(self, leg_m: Mapping[tuple[Coordinate, Coordinate], int], *, gate: Gate | None = None) -> None:
        self._leg_m = leg_m
        self.gate = gate or Gate()
        self.asked: Counter[tuple[Coordinate, Coordinate]] = Counter()

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def matrix(self, sources: Sequence[Coordinate], targets: Sequence[Coordinate]) -> Sequence[Sequence[int]]:
        self.gate.passing()
        self.asked.update((source, target) for source in sources for target in targets)
        return [[self._leg_m[source, target] for target in targets] for source in sources]

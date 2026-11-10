"""PlanRunRepository port (brief §6, ADR-006) and the unit of work planning reads and writes through."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from overland_planner.application.ports.project_snapshot_reader import ProjectSnapshotReader
from overland_planner.application.ports.unit_of_work import UnitOfWork
from overland_planner.domain.planning.plan_run import PlanReport, PlanRun, PlanRunStatus, PlanStop, Totals
from overland_planner.domain.planning.run_messages import NotFullyOptimised


@dataclass(frozen=True)
class PlanRunDetail:
    """A stored plan run with its itinerary and totals; a Failed run, or one stored before 0006, has no totals. A run
    stored before 0008 reads `reproducible` true and no `not_fully_optimised`. `memo_hit` is the stored column, which
    the run queries derive from `memo_source_run_id` for a run with a `run_time_ms` (06-10); a run stored before has
    neither. `items_planned` counts the Included items other than the anchors it was planned with. `messages` are the
    lines the run shows, which the run queries fill (D223 b); the repository reads none."""

    id: str
    project_id: str
    number: int
    status: PlanRunStatus
    failure_reason: str | None
    stops: tuple[PlanStop, ...]
    totals: Totals | None = None
    report: PlanReport | None = None
    reproducible: bool = True
    not_fully_optimised: NotFullyOptimised | None = None
    messages: tuple[str, ...] = ()
    memo_hit: bool = False
    run_time_ms: int | None = None
    memo_source_run_id: str | None = None
    items_planned: int | None = None


@dataclass(frozen=True)
class NewPlanRun:
    """The row a finished plan writes: its number comes from the same transaction (brief section 8).

    `fingerprint` is the solver inputs' memo key, null for a job without a memo; `memo_hit` says the order was reused.
    `reproducible` and `not_fully_optimised` are the run flags of how its search ended (brief section 8); a memo hit
    inherits its source's. `run_time_ms` is from the job's start to the run stored; `memo_source_run_id` names the run
    a memo hit reused (06-10).
    """

    id: str
    project_id: str
    number: int
    status: PlanRunStatus
    failure_reason: str | None
    created_at: datetime
    revision: int
    provider_id: str
    objective: str
    inputs: Mapping[str, object]
    stops: tuple[PlanStop, ...]
    totals: Totals | None = None
    report: PlanReport | None = None
    fingerprint: str | None = None
    memo_hit: bool = False
    reproducible: bool = True
    not_fully_optimised: NotFullyOptimised | None = None
    run_time_ms: int | None = None
    memo_source_run_id: str | None = None


class PlanRunRepository(Protocol):
    def list(self, project_id: str) -> list[PlanRun]:
        """The project's plan runs, ordered by number."""
        ...

    def get(self, plan_run_id: str) -> PlanRunDetail | None: ...

    def next_number(self, project_id: str) -> int:
        """The number the project's next plan run gets: the first is 1."""
        ...

    def add(self, run: NewPlanRun) -> None: ...

    def latest_ready(self, project_id: str, fingerprint: str) -> PlanRunDetail | None:
        """The project's ready run of the highest number stored with `fingerprint`: the memo source (ADR-014 §5)."""
        ...


class PlanningUnitOfWork(UnitOfWork, Protocol):
    """A unit of work exposing planning's repositories bound to its transaction."""

    @property
    def plan_runs(self) -> PlanRunRepository: ...

    @property
    def project_snapshots(self) -> ProjectSnapshotReader: ...

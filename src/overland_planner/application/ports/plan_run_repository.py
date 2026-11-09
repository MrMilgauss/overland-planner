"""PlanRunRepository port (brief §6, ADR-006) and the unit of work planning reads and writes through."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from overland_planner.application.ports.project_snapshot_reader import ProjectSnapshotReader
from overland_planner.application.ports.unit_of_work import UnitOfWork
from overland_planner.domain.planning.plan_run import PlanRun, PlanRunStatus, PlanStop, Totals
from overland_planner.domain.planning.plan_run_assembler import PlanReport


@dataclass(frozen=True)
class PlanRunDetail:
    """A stored plan run with its itinerary and totals; a Failed run, or one stored before 0006, has no totals."""

    id: str
    project_id: str
    number: int
    status: PlanRunStatus
    failure_reason: str | None
    stops: tuple[PlanStop, ...]
    totals: Totals | None = None
    report: PlanReport | None = None


@dataclass(frozen=True)
class NewPlanRun:
    """The row a finished plan writes: its number comes from the same transaction (brief section 8)."""

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


class PlanRunRepository(Protocol):
    def list(self, project_id: str) -> list[PlanRun]:
        """The project's plan runs, ordered by number."""
        ...

    def get(self, plan_run_id: str) -> PlanRunDetail | None: ...

    def next_number(self, project_id: str) -> int:
        """The number the project's next plan run gets: the first is 1."""
        ...

    def add(self, run: NewPlanRun) -> None: ...


class PlanningUnitOfWork(UnitOfWork, Protocol):
    """A unit of work exposing planning's repositories bound to its transaction."""

    @property
    def plan_runs(self) -> PlanRunRepository: ...

    @property
    def project_snapshots(self) -> ProjectSnapshotReader: ...

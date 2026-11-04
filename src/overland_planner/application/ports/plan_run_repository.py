"""PlanRunRepository port (brief §6, ADR-006) and the unit of work planning reads and writes through."""

from __future__ import annotations

from typing import Protocol

from overland_planner.application.ports.project_snapshot_reader import ProjectSnapshotReader
from overland_planner.application.ports.unit_of_work import UnitOfWork
from overland_planner.domain.planning.plan_run import PlanRun


class PlanRunRepository(Protocol):
    def list(self, project_id: str) -> list[PlanRun]:
        """The project's plan runs, ordered by number."""
        ...


class PlanningUnitOfWork(UnitOfWork, Protocol):
    """A unit of work exposing planning's repositories bound to its transaction."""

    @property
    def plan_runs(self) -> PlanRunRepository: ...

    @property
    def project_snapshots(self) -> ProjectSnapshotReader: ...

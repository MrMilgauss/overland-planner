"""Plan run queries (US-02b, brief §5): the plan runs of a project; a job still running has none."""

from __future__ import annotations

from collections.abc import Callable

from overland_planner.application.catalog.facade import ProjectNotFoundError
from overland_planner.application.ports.plan_run_repository import PlanningUnitOfWork, PlanRunDetail
from overland_planner.domain.planning.plan_run import PlanRun
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot


class PlanRunNotFoundError(LookupError):
    """No plan run has this id."""


def existing_snapshot(uow: PlanningUnitOfWork, project_id: str) -> ProjectSnapshot:
    """The project as planning sees it in this unit of work; raises `ProjectNotFoundError` when there is none."""
    snapshot = uow.project_snapshots.read(project_id)
    if snapshot is None:
        raise ProjectNotFoundError(project_id)
    return snapshot


class PlanRunQueries:
    def __init__(self, unit_of_work: Callable[[], PlanningUnitOfWork]) -> None:
        self._unit_of_work = unit_of_work

    def list(self, project_id: str) -> list[PlanRun]:
        """The project's plan runs, ordered by number, each Stale or not. Raises `ProjectNotFoundError`."""
        with self._unit_of_work() as uow:
            existing_snapshot(uow, project_id)
            revision = uow.project_snapshots.stamp(project_id).revision
            return [run.seen_at(revision) for run in uow.plan_runs.list(project_id)]

    def get(self, plan_run_id: str) -> PlanRunDetail | None:
        """The stored run with its itinerary and totals, or `None` for an unknown id."""
        with self._unit_of_work() as uow:
            return uow.plan_runs.get(plan_run_id)

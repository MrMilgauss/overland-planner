"""Plan run queries (US-02b, brief §5): the plan runs of a project; a job still running has none.

A run's detail shows the lines composed from its stored facts (`run_messages`, D223 b), a memo hit naming its source
run's number. `memo_hit` is true exactly when the run names a memo source; a run stored before 06-10 (no run time)
keeps its stored `memo_hit` column. A Calculate's notices follow the project's Included items other than its anchors
(D146).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from overland_planner.application.catalog.facade import ProjectNotFoundError
from overland_planner.application.ports.plan_run_repository import PlanningUnitOfWork, PlanRunDetail
from overland_planner.domain.planning.plan_run import PlanRun
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.run_messages import project_notices, run_messages
from overland_planner.domain.routing.provider_label import provider_header


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
        """The stored run with its itinerary, totals and the lines it shows, or `None` for an unknown id."""
        with self._unit_of_work() as uow:
            detail = uow.plan_runs.get(plan_run_id)
            source_id = None if detail is None else detail.memo_source_run_id
            source = None if source_id is None else uow.plan_runs.get(source_id)
        if detail is None:
            return None
        messages = run_messages(
            detail.not_fully_optimised,
            failure_reason=detail.failure_reason,
            number=detail.number,
            items_planned=detail.items_planned,
            run_time_ms=detail.run_time_ms,
            reused_from=None if source is None else source.number,
            items=() if detail.report is None else detail.report.items,
        )
        memo_hit = detail.memo_hit if detail.run_time_ms is None else source_id is not None
        header = "" if detail.provider_id is None else provider_header(detail.provider_id, detail.profile)
        return replace(detail, messages=messages, memo_hit=memo_hit, provider_header=header)

    def notices(self, project_id: str) -> tuple[str, ...]:
        """What a Calculate of the project says first (D146). Raises `ProjectNotFoundError`."""
        with self._unit_of_work() as uow:
            snapshot = existing_snapshot(uow, project_id)
        return project_notices(len(snapshot.visited_items()))

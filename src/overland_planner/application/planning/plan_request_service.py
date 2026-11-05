"""Plan request use case (US-02b, brief §8): Calculate's pre-checks, in brief order: anchors, active job, optimizer.

A refused request creates no job and no plan run and logs one `plan.job.refused` line. The optimizer's readiness is the
start-up probe outcome of the component `tour_solver`; nothing probes it again. A request that passes every pre-check
starts a plan job and answers at once with its id. The registry decides the active job check again as it starts the job,
atomically, so of two fast presses that both passed the pre-checks only one gets a job.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from overland_planner.application.planning.plan_job_registry import PlanJobRegistry
from overland_planner.application.planning.plan_run_queries import existing_snapshot
from overland_planner.application.platform.facade import HealthService
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.plan_run_repository import PlanningUnitOfWork
from overland_planner.domain.planning.project_snapshot import Anchor, ProjectSnapshot

_OPTIMIZER_COMPONENT = "tour_solver"


class PlanRefusedError(Exception):
    """Calculate was refused by a pre-check: no job and no plan run."""

    reason: ClassVar[str]
    http_status: ClassVar[int]


class MissingAnchorError(PlanRefusedError):
    reason = "missing_anchor"
    http_status = 422

    def __init__(self, anchor: Anchor) -> None:
        super().__init__(f"Set the {anchor} before calculating")


class JobActiveError(PlanRefusedError):
    reason = "job_active"
    http_status = 409

    def __init__(self) -> None:
        super().__init__("A plan is already being calculated for this project")


class OptimizerUnavailableError(PlanRefusedError):
    reason = "optimizer_unavailable"
    http_status = 503

    def __init__(self) -> None:
        super().__init__("Optimizer unavailable - nothing was changed")


class PlanRequestService:
    def __init__(
        self,
        unit_of_work: Callable[[], PlanningUnitOfWork],
        health: HealthService,
        event_log: EventLog,
        jobs: PlanJobRegistry,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._health = health
        self._event_log = event_log
        self._jobs = jobs

    def request(self, project_id: str) -> str:
        """The started job's id. Raises `ProjectNotFoundError` or the `PlanRefusedError` of the failed pre-check."""
        with self._unit_of_work() as uow:
            snapshot = existing_snapshot(uow, project_id)
        refusal = self._first_refusal(project_id, snapshot)
        if refusal is None:
            job_id = self._jobs.start(project_id)
            if job_id is not None:
                return job_id
            refusal = JobActiveError()
        self._event_log.info(
            "plan.job.refused", project_id=project_id, http_status=refusal.http_status, reason=refusal.reason
        )
        raise refusal

    def _first_refusal(self, project_id: str, snapshot: ProjectSnapshot) -> PlanRefusedError | None:
        anchor = snapshot.missing_anchor()
        if anchor is not None:
            return MissingAnchorError(anchor)
        if self._jobs.has_active_job(project_id):
            return JobActiveError()
        if self._health.detail().components[_OPTIMIZER_COMPONENT].outcome != "ok":
            return OptimizerUnavailableError()
        return None

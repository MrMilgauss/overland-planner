"""Planning HTTP routes (brief §5, §8): Calculate, polling and stopping its job, and a project's plan runs."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from overland_planner.adapters.http.schemas import (
    CALCULATE_ERROR_RESPONSES,
    ERROR_RESPONSES,
    PlanJobAccepted,
    PlanJobResource,
    PlanRunDetailResource,
    PlanRunResource,
)
from overland_planner.application.planning.facade import (
    PlanJobRegistry,
    PlanRequestService,
    PlanRunNotFoundError,
    PlanRunQueries,
)

_NOT_FOUND = 404


@dataclass(frozen=True)
class PlanningUseCases:
    """The planning application services behind the plan routes."""

    requests: PlanRequestService
    jobs: PlanJobRegistry
    runs: PlanRunQueries


def planning_routes(use_cases: PlanningUseCases) -> APIRouter:
    requests, jobs, runs = use_cases.requests, use_cases.jobs, use_cases.runs
    router = APIRouter(prefix="/api")

    @router.post("/projects/{project_id}/plan-runs", status_code=202, responses=CALCULATE_ERROR_RESPONSES)
    def calculate(project_id: str, ignore_memo: bool = False) -> PlanJobAccepted:
        """Answers at once with the job to poll. Refused with 422 `missing_anchor`, 409 `job_active` or 503
        `optimizer_unavailable`: no job and no plan run. `ignore_memo=true` ("Re-optimise (ignore previous result)")
        has the same refusals; a value that is not a boolean answers 422 `validation_error`."""
        return PlanJobAccepted(job_id=requests.request(project_id, ignore_memo=ignore_memo))

    @router.get("/plan-jobs/{job_id}", responses=ERROR_RESPONSES)
    def plan_job(job_id: str) -> PlanJobResource:
        """`plan_run_id` stays null until the run is stored. 404 `not_found` for an unknown or expired id."""
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(_NOT_FOUND, "Plan job not found")
        return PlanJobResource.of(job)

    @router.post("/plan-jobs/{job_id}/stop", responses=ERROR_RESPONSES)
    def stop_plan_job(job_id: str) -> PlanJobResource:
        """ "Stop and use best so far" (US-06b, D136): always 200 with the current poll payload, repeated Stops change
        nothing. While solving the job ends with the best route so far, labelled, or Failed `stopped` without one;
        before solving it ends `cancelled` with no run; once `stoppable` is false the run being written completes.
        404 `not_found` for an unknown or expired id."""
        job = jobs.stop(job_id)
        if job is None:
            raise HTTPException(_NOT_FOUND, "Plan job not found")
        return PlanJobResource.of(job)

    @router.get("/projects/{project_id}/plan-runs", responses=ERROR_RESPONSES)
    def project_plan_runs(project_id: str) -> list[PlanRunResource]:
        return [PlanRunResource.of(run) for run in runs.list(project_id)]

    @router.get("/plan-runs/{plan_run_id}", responses=ERROR_RESPONSES)
    def plan_run(plan_run_id: str) -> PlanRunDetailResource:
        """The stops in order, track stops with their entry and exit, and the unrounded totals; a Failed run has no
        stops and no totals and names its reason; a run stored before the totals were shows `totals` null."""
        run = runs.get(plan_run_id)
        if run is None:
            raise PlanRunNotFoundError(plan_run_id)
        return PlanRunDetailResource.of(run)

    return router

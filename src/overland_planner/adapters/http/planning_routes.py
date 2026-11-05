"""Planning HTTP routes (brief §5, §8): Calculate, polling its job, and a project's plan runs."""

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
from overland_planner.application.planning.facade import PlanJobRegistry, PlanRequestService, PlanRunQueries

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
    def calculate(project_id: str) -> PlanJobAccepted:
        """Answers at once with the job to poll. Refused with 422 `missing_anchor`, 409 `job_active` or 503
        `optimizer_unavailable`: no job and no plan run."""
        return PlanJobAccepted(job_id=requests.request(project_id))

    @router.get("/plan-jobs/{job_id}", responses=ERROR_RESPONSES)
    def plan_job(job_id: str) -> PlanJobResource:
        """`plan_run_id` stays null until the run is stored. 404 `not_found` for an unknown or expired id."""
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(_NOT_FOUND, "Plan job not found")
        return PlanJobResource.of(job)

    @router.get("/projects/{project_id}/plan-runs", responses=ERROR_RESPONSES)
    def project_plan_runs(project_id: str) -> list[PlanRunResource]:
        return [PlanRunResource.of(run) for run in runs.list(project_id)]

    @router.get("/plan-runs/{plan_run_id}", responses=ERROR_RESPONSES)
    def plan_run(plan_run_id: str) -> PlanRunDetailResource:
        """The stops in order, track stops with their entry and exit; a Failed run has no stops and names its reason."""
        run = runs.get(plan_run_id)
        if run is None:
            raise HTTPException(_NOT_FOUND, "Plan run not found")
        return PlanRunDetailResource.of(run)

    return router

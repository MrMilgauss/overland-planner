"""Planning HTTP routes (brief §5, §8): Calculate and a project's plan runs."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from overland_planner.adapters.http.schemas import CALCULATE_ERROR_RESPONSES, ERROR_RESPONSES, PlanRunResource
from overland_planner.application.planning.facade import PlanRequestService, PlanRunQueries


@dataclass(frozen=True)
class PlanningUseCases:
    """The planning application services behind the plan-runs routes."""

    requests: PlanRequestService
    runs: PlanRunQueries


def planning_routes(use_cases: PlanningUseCases) -> APIRouter:
    requests, runs = use_cases.requests, use_cases.runs
    router = APIRouter(prefix="/api/projects")

    @router.post("/{project_id}/plan-runs", status_code=202, responses=CALCULATE_ERROR_RESPONSES)
    def calculate(project_id: str) -> None:
        """Refused with 422 `missing_anchor` or 503 `optimizer_unavailable`: no job and no plan run."""
        requests.request(project_id)

    @router.get("/{project_id}/plan-runs", responses=ERROR_RESPONSES)
    def project_plan_runs(project_id: str) -> list[PlanRunResource]:
        return [PlanRunResource.of(run) for run in runs.list(project_id)]

    return router

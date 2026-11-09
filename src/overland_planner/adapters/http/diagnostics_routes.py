"""Diagnostics HTTP route (DV-3, kpi-contracts `diagnostics_endpoint`): `GET /api/diagnostics[?days=&project_id=]`.

Read-only, behind the household password when it is on, like every /api path. `days` is 1-365 (default 30), anything
else answers 422 `validation_error`; an unknown `project_id` answers 404 `not_found`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from overland_planner.adapters.http.schemas import ERROR_RESPONSES, DiagnosticsResource
from overland_planner.application.platform.facade import DiagnosticsService, UnknownProjectError

_NOT_FOUND = 404


def diagnostics_routes(diagnostics: DiagnosticsService) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/diagnostics", responses=ERROR_RESPONSES)
    def read_diagnostics(
        days: Annotated[int, Query(ge=1, le=365)] = 30, project_id: str | None = None
    ) -> DiagnosticsResource:
        """K2, K3, K5 and K7 over the last `days` days; `project_id` limits every figure to that project."""
        try:
            report = diagnostics.report(days=days, project_id=project_id)
        except UnknownProjectError as unknown:
            raise HTTPException(_NOT_FOUND, "Project not found") from unknown
        return DiagnosticsResource.of(report)

    return router

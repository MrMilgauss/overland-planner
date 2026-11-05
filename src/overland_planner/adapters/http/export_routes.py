"""Export HTTP route (brief §5): a stored plan run as a GPX download."""

from __future__ import annotations

from fastapi import APIRouter, Response

from overland_planner.adapters.http.schemas import ERROR_RESPONSES
from overland_planner.application.export.facade import GpxExportService

_GPX_MEDIA_TYPE = "application/gpx+xml"


def export_routes(exports: GpxExportService) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get(
        "/plan-runs/{plan_run_id}/export.gpx",
        response_class=Response,
        responses={200: {"content": {_GPX_MEDIA_TYPE: {}}, "description": "The GPX file"}, **ERROR_RESPONSES},
    )
    def export_gpx(plan_run_id: str) -> Response:
        """Changes nothing. 404 `not_found` for an unknown run; 422 `validation_error` when a track's stored points are
        not the ones the run recorded. A sync handler, so a big track never holds up the event loop."""
        return Response(
            exports.export(plan_run_id),
            media_type=_GPX_MEDIA_TYPE,
            headers={"Content-Disposition": "attachment"},
        )

    return router

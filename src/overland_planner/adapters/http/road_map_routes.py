"""Road-map HTTP routes (D308): `GET /api/road-map` names the map the engine serves; `GET /api/projects/{id}/coverage`
judges a trip against it."""

from __future__ import annotations

from fastapi import APIRouter

from overland_planner.adapters.http.schemas import (
    ERROR_RESPONSES,
    CoverageBody,
    RoadMapBody,
    RoadMapChangeBody,
    ServedMapBody,
)
from overland_planner.application.roadmap.facade import CoverageService, RoadMapService


def road_map_routes(service: RoadMapService, coverage: CoverageService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/road-map")
    def road_map() -> RoadMapBody:
        # No change is ever planned yet: the queue arrives with the change routes.
        return RoadMapBody(served=ServedMapBody.of(service.served()), change=RoadMapChangeBody(state="none"))

    @router.get("/api/projects/{project_id}/coverage", responses=ERROR_RESPONSES)
    def trip_coverage(project_id: str) -> CoverageBody:
        return CoverageBody.of(coverage.of(project_id))

    return router

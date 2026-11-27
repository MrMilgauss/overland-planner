"""Road-map HTTP routes (D308): `GET /api/road-map` names the map the engine serves."""

from __future__ import annotations

from fastapi import APIRouter

from overland_planner.adapters.http.schemas import RoadMapBody, RoadMapChangeBody, ServedMapBody
from overland_planner.application.roadmap.facade import RoadMapService


def road_map_routes(service: RoadMapService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/road-map")
    def road_map() -> RoadMapBody:
        # No change is ever planned yet: the queue arrives with the change routes.
        return RoadMapBody(served=ServedMapBody.of(service.served()), change=RoadMapChangeBody(state="none"))

    return router

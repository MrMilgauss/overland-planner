"""Road-map HTTP routes (D308): `GET /api/road-map` names the map the engine serves; `GET /api/road-map/catalogue?q=`
searches the free list of regions by name (two letters at least); `GET /api/projects/{id}/coverage` judges a trip
against the served map."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from overland_planner.adapters.http.errors import envelope
from overland_planner.adapters.http.schemas import (
    CATALOGUE_ERROR_RESPONSES,
    ERROR_RESPONSES,
    CatalogueBody,
    CoverageBody,
    RoadMapBody,
    RoadMapChangeBody,
    ServedMapBody,
)
from overland_planner.application.roadmap.facade import (
    CatalogueUnavailableError,
    CoverageService,
    RoadMapService,
    SearchTooShortError,
)


def road_map_routes(service: RoadMapService, coverage: CoverageService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/road-map")
    def road_map() -> RoadMapBody:
        # No change is ever planned yet: the queue arrives with the change routes.
        return RoadMapBody(served=ServedMapBody.of(service.served()), change=RoadMapChangeBody(state="none"))

    @router.get("/api/road-map/catalogue", response_model=CatalogueBody, responses=CATALOGUE_ERROR_RESPONSES)
    def catalogue(q: str = "") -> CatalogueBody | JSONResponse:
        try:
            return CatalogueBody.of(service.search_catalogue(q))
        except SearchTooShortError as short:
            raise HTTPException(status_code=422, detail=str(short)) from None
        except CatalogueUnavailableError:
            return envelope(
                503,
                "region_catalogue_unavailable",
                "The list of regions cannot be reached right now - try again later",
            )

    @router.get("/api/projects/{project_id}/coverage", responses=ERROR_RESPONSES)
    def trip_coverage(project_id: str) -> CoverageBody:
        return CoverageBody.of(coverage.of(project_id))

    return router

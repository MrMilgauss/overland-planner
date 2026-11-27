"""`GET /api/places/search?q=` (D307, ADR-019): up to five places for a typed name, each with its region. A name of
fewer than two letters is a 422 and sends nothing; a search that cannot be answered is a 503
`place_search_unavailable`."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from overland_planner.adapters.http.errors import envelope
from overland_planner.adapters.http.schemas import PLACE_SEARCH_ERROR_RESPONSES, PlaceBody
from overland_planner.application.roadmap.facade import (
    PlaceNameTooShortError,
    PlaceSearchService,
    PlaceSearchUnavailableError,
)


def place_routes(service: PlaceSearchService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/places/search", response_model=list[PlaceBody], responses=PLACE_SEARCH_ERROR_RESPONSES)
    def search(q: str = "") -> list[PlaceBody] | JSONResponse:
        try:
            return [PlaceBody.of(hit) for hit in service.search(q)]
        except PlaceNameTooShortError as short:
            raise HTTPException(status_code=422, detail=str(short)) from None
        except PlaceSearchUnavailableError:
            return envelope(503, "place_search_unavailable", "Place search is not available right now")

    return router

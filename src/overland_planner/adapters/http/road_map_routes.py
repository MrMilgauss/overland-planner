"""Road-map HTTP routes (D308): `GET /api/road-map` names the map the engine serves, the change that waits and the
limits; `GET /api/road-map/catalogue?q=` searches the free list of regions by name (two letters at least);
`POST /api/road-map/change/preview` summarises a change without writing it; `POST /api/road-map/change` keeps it ready
for the helper and `DELETE /api/road-map/change` cancels it while the helper has not taken it;
`GET /api/projects/{id}/coverage` judges a trip against the served map."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response

from overland_planner.adapters.http.errors import envelope
from overland_planner.adapters.http.schemas import (
    CANCEL_ERROR_RESPONSES,
    CATALOGUE_ERROR_RESPONSES,
    CHANGE_ERROR_RESPONSES,
    ERROR_RESPONSES,
    PREVIEW_ERROR_RESPONSES,
    CatalogueBody,
    ChangePreviewRequest,
    ChangeSummaryBody,
    CoverageBody,
    RoadMapBody,
    RoadMapChangeBody,
    RoadMapLimitsBody,
    ServedMapBody,
)
from overland_planner.application.roadmap.facade import (
    CatalogueUnavailableError,
    ChangesUnavailableError,
    CoverageService,
    Refusal,
    RoadMapService,
    SearchTooShortError,
)
from overland_planner.domain.roadmap.estimate import BYTES_PER_GB


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


_CONFLICTS = {"change_pending", "rebuild_running"}


def _refused(refused: Refusal) -> JSONResponse:
    """422 for a change the rules refuse, 409 while another is waiting or running; same_day names when to retry."""
    body: dict[str, object] = {"code": refused.code, "message": refused.message}
    when = refused.details.get("next_rebuild_from")
    if isinstance(when, datetime):
        body["next_rebuild_from"] = _utc(when).strftime("%Y-%m-%dT%H:%M:%SZ")
    if refused.code == "rebuilds_not_set_up":
        return JSONResponse(body, status_code=503)
    return JSONResponse(body, status_code=409 if refused.code in _CONFLICTS else 422)


def _changes_unavailable() -> JSONResponse:
    return envelope(503, "changes_unavailable", "Changing the road map is not available right now")


def _catalogue_unavailable() -> JSONResponse:
    return envelope(
        503, "region_catalogue_unavailable", "The list of regions cannot be reached right now - try again later"
    )


def road_map_routes(service: RoadMapService, coverage: CoverageService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/road-map")
    def road_map() -> RoadMapBody:
        change = service.planned_change()
        return RoadMapBody(
            served=ServedMapBody.of(service.served()),
            change=RoadMapChangeBody.of(change),
            limits=RoadMapLimitsBody(
                changes_available=service.changes_available(),
                max_gb=service.max_gb,
                max_bytes=int(service.max_gb * BYTES_PER_GB),
                next_rebuild_from=service.next_rebuild_from(),
                helper_seen_at=service.helper_seen_at(),
                rebuilds_set_up=service.rebuilds_set_up(),
            ),
            planning_paused=change is not None and change.planning_paused,
            planning_back_at=None if change is None else change.planning_back_at,
            server_utc_offset_minutes=service.utc_offset_minutes(),
        )

    @router.get("/api/road-map/catalogue", response_model=CatalogueBody, responses=CATALOGUE_ERROR_RESPONSES)
    def catalogue(q: str = "") -> CatalogueBody | JSONResponse:
        try:
            return CatalogueBody.of(service.search_catalogue(q))
        except SearchTooShortError as short:
            raise HTTPException(status_code=422, detail=str(short)) from None
        except CatalogueUnavailableError:
            return _catalogue_unavailable()

    @router.post("/api/road-map/change/preview", response_model=ChangeSummaryBody, responses=PREVIEW_ERROR_RESPONSES)
    def preview(request: ChangePreviewRequest) -> ChangeSummaryBody | JSONResponse:
        try:
            return ChangeSummaryBody.of(service.preview_change(request.region_keys))
        except Refusal as refused:
            return envelope(422, refused.code, refused.message)
        except CatalogueUnavailableError:
            return _catalogue_unavailable()

    @router.post(
        "/api/road-map/change", status_code=201, response_model=ChangeSummaryBody, responses=CHANGE_ERROR_RESPONSES
    )
    def plan_change(request: ChangePreviewRequest) -> ChangeSummaryBody | JSONResponse:
        start_at = None if request.start_at is None else _utc(request.start_at)
        try:
            return ChangeSummaryBody.of(service.plan_change(request.region_keys, start_at))
        except ChangesUnavailableError:
            return _changes_unavailable()
        except Refusal as refused:
            return _refused(refused)
        except CatalogueUnavailableError:
            return _catalogue_unavailable()

    @router.delete("/api/road-map/change", status_code=204, responses=CANCEL_ERROR_RESPONSES)
    def cancel_change() -> Response:
        try:
            cancelled = service.cancel_change()
        except ChangesUnavailableError:
            return _changes_unavailable()
        if not cancelled:
            return envelope(
                409, "change_not_pending", "No change is waiting: the rebuild has already started, or none was planned"
            )
        return Response(status_code=204)

    @router.get("/api/projects/{project_id}/coverage", responses=ERROR_RESPONSES)
    def trip_coverage(project_id: str) -> CoverageBody:
        return CoverageBody.of(coverage.of(project_id))

    return router

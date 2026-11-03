"""Catalog HTTP routes (brief §5): create, list and open projects, import track files and list a project's items."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from overland_planner.adapters.http.schemas import ERROR_RESPONSES, ItemResource, ProjectCreate, ProjectResource
from overland_planner.adapters.http.upload_limits import FILES_FIELD, UploadLimits, read_track_files
from overland_planner.application.catalog.facade import ProjectService, TrackImportService

# The body is read by `read_track_files` (bounded, never spooled to disk), so the schema is declared here.
_TRACK_UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": [FILES_FIELD],
                    "properties": {
                        FILES_FIELD: {
                            "type": "array",
                            "title": "Files",
                            "items": {"type": "string", "contentMediaType": "application/octet-stream"},
                        }
                    },
                }
            }
        },
    }
}


def catalog_routes(catalog: ProjectService, imports: TrackImportService, limits: UploadLimits) -> APIRouter:
    router = APIRouter(prefix="/api/projects", responses=ERROR_RESPONSES)

    @router.post("", status_code=201)
    def create_project(body: ProjectCreate) -> ProjectResource:
        return ProjectResource.of(catalog.create(body.name))

    @router.get("")
    def list_projects() -> list[ProjectResource]:
        return [ProjectResource.of(project) for project in catalog.list()]

    @router.get("/{project_id}")
    def open_project(project_id: str) -> ProjectResource:
        return ProjectResource.of(catalog.open(project_id))

    @router.post("/{project_id}/tracks", status_code=201, openapi_extra=_TRACK_UPLOAD_BODY)
    async def import_tracks(project_id: str, request: Request) -> list[ItemResource]:
        """All or nothing (D149): when any file is refused, 422 (or 413 for the caps) names it and nothing is added."""
        uploads = await read_track_files(request, limits)
        items = await run_in_threadpool(imports.import_files, project_id, uploads)
        return [ItemResource.of(item) for item in items]

    @router.get("/{project_id}/items")
    def project_items(project_id: str) -> list[ItemResource]:
        return [ItemResource.of(item) for item in catalog.items(project_id)]

    return router

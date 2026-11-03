"""Catalog HTTP routes (brief §5): create, list and open projects, import track files and list a project's items."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from overland_planner.adapters.http.schemas import ERROR_RESPONSES, ItemResource, ProjectCreate, ProjectResource
from overland_planner.application.catalog.facade import ProjectService, TrackFile, TrackImportService


def catalog_routes(catalog: ProjectService, imports: TrackImportService) -> APIRouter:
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

    @router.post("/{project_id}/tracks", status_code=201)
    def import_tracks(project_id: str, files: Annotated[list[UploadFile], File()]) -> list[ItemResource]:
        """All or nothing (D149): when any file is refused, 422 names each refused file and nothing is added."""
        uploads = [TrackFile(upload.filename or "upload.gpx", upload.file.read()) for upload in files]
        return [ItemResource.of(item) for item in imports.import_files(project_id, uploads)]

    @router.get("/{project_id}/items")
    def project_items(project_id: str) -> list[ItemResource]:
        return [ItemResource.of(item) for item in catalog.items(project_id)]

    return router

"""Catalog HTTP routes (brief §5): create, list and open projects, and the item list of a project."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from overland_planner.adapters.http.schemas import ERROR_RESPONSES, ProjectCreate, ProjectResource
from overland_planner.application.catalog.facade import ProjectService


def catalog_routes(catalog: ProjectService) -> APIRouter:
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

    @router.get("/{project_id}/items")
    def project_items(project_id: str) -> list[Any]:
        return list(catalog.items(project_id))

    return router

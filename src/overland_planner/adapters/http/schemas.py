"""HTTP request/response bodies (brief §5, D130): snake_case fields, ids as strings."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from overland_planner.domain.catalog.project import Project


class ErrorEnvelope(BaseModel):
    """Every non-2xx answer under /api (D183)."""

    code: str
    message: str


class ProjectCreate(BaseModel):
    name: str


class ProjectResource(BaseModel):
    id: str
    name: str
    revision: int

    @classmethod
    def of(cls, project: Project) -> ProjectResource:
        return cls(id=project.id, name=project.name.value, revision=project.revision)


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "not_found"},
    422: {"model": ErrorEnvelope, "description": "validation_error"},
}

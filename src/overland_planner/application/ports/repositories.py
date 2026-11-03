"""Repository ports (brief §6, ADR-006): bound to one unit of work; changes are durable only on its `commit()`."""

from __future__ import annotations

from typing import Protocol

from overland_planner.application.ports.unit_of_work import UnitOfWork
from overland_planner.domain.catalog.project import Project


class ProjectRepository(Protocol):
    def add(self, project: Project) -> None: ...

    def get(self, project_id: str) -> Project | None: ...

    def list(self) -> list[Project]:
        """Every project, oldest first."""
        ...


class CatalogUnitOfWork(UnitOfWork, Protocol):
    """A unit of work exposing the catalog repositories bound to its transaction."""

    @property
    def projects(self) -> ProjectRepository: ...

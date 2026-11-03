"""Catalog use cases on trip projects (brief §3, §5): create, list and open; one unit of work per use case."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence

from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.repositories import CatalogUnitOfWork
from overland_planner.domain.catalog.item import CatalogItem
from overland_planner.domain.catalog.project import Project, ProjectName


class ProjectNotFoundError(LookupError):
    def __init__(self, project_id: str) -> None:
        super().__init__(f"No project with id {project_id}")


class ProjectService:
    def __init__(self, unit_of_work: Callable[[], CatalogUnitOfWork], clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def create(self, name: str) -> Project:
        """Raises `ProjectNameRequiredError` (nothing is stored) when the name is blank."""
        project = Project.create(uuid.uuid4().hex, ProjectName(name), self._clock.now())
        with self._unit_of_work() as uow:
            uow.projects.add(project)
            uow.commit()
        return project

    def list(self) -> list[Project]:
        with self._unit_of_work() as uow:
            return uow.projects.list()

    def open(self, project_id: str) -> Project:
        with self._unit_of_work() as uow:
            project = uow.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project

    def items(self, project_id: str) -> Sequence[CatalogItem]:
        """The open project's items in the order they were added; empty for a new project."""
        with self._unit_of_work() as uow:
            if uow.projects.get(project_id) is None:
                raise ProjectNotFoundError(project_id)
            return uow.items.list(project_id)

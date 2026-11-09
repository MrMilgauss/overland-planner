"""Catalog use cases on trip projects (brief §3, §5): create, list, open, set the off-road speed, list and remove items;
one unit of work each.

Removing an item clears any anchor it held and raises the project revision once (slice 02, US-04 S2/S3). The plan runs
and a removed track's files are not touched (ADR-018 Revision 2: sweep-only deletion).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence

from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.repositories import CatalogUnitOfWork
from overland_planner.domain.catalog.item import CatalogItem, ItemType
from overland_planner.domain.catalog.project import OffroadSpeed, Project, ProjectName


class ProjectNotFoundError(LookupError):
    def __init__(self, project_id: str) -> None:
        super().__init__(f"No project with id {project_id}")


class ItemNotFoundError(LookupError):
    def __init__(self, item_id: str) -> None:
        super().__init__(f"No item with id {item_id}")


def existing_project(uow: CatalogUnitOfWork, project_id: str) -> Project:
    """The project in this unit of work; raises `ProjectNotFoundError` when there is none."""
    project = uow.projects.get(project_id)
    if project is None:
        raise ProjectNotFoundError(project_id)
    return project


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
            return existing_project(uow, project_id)

    def items(self, project_id: str, item_type: ItemType | None = None) -> Sequence[CatalogItem]:
        """The open project's items (of `item_type` when given) in the order added, each with its anchor."""
        with self._unit_of_work() as uow:
            project = existing_project(uow, project_id)
            listed = uow.items.list(project_id)
            return project.anchors.marked(item for item in listed if item_type in (None, item.type))

    def remove_item(self, project_id: str, item_id: str) -> None:
        """Raises `ProjectNotFoundError`, or `ItemNotFoundError` for an item not in the project; nothing changes."""
        with self._unit_of_work() as uow:
            project = existing_project(uow, project_id)
            item = uow.items.get(item_id)
            if item is None or item.project_id != project_id:
                raise ItemNotFoundError(item_id)
            uow.projects.update(project.item_removed(item_id))
            uow.items.remove(item_id)
            uow.commit()

    def set_offroad_speed(self, project_id: str, kmh: float) -> Project:
        """Raises `ProjectNotFoundError`, or `OffroadSpeedNotDrivableError` for 0, less or a non-finite speed; nothing
        changes then. Otherwise one more catalog change (revision + 1)."""
        with self._unit_of_work() as uow:
            project = existing_project(uow, project_id).with_offroad_speed(OffroadSpeed(kmh))
            uow.projects.update(project)
            uow.commit()
        return project

"""Anchor use case (US-02c, HC-2, brief §5): set the Start and End of a trip among the project's POIs.

New anchors replace the previous ones in one unit of work that increments the project revision once. An unknown
project or item is not found; a track (D6) or an item of another project is refused; either way nothing changes.
"""

from __future__ import annotations

from collections.abc import Callable

from overland_planner.application.catalog.project_service import ProjectNotFoundError
from overland_planner.application.ports.repositories import CatalogUnitOfWork
from overland_planner.domain.catalog.anchors import Anchors
from overland_planner.domain.catalog.item import CatalogItem
from overland_planner.domain.catalog.project import Project


class ItemNotFoundError(LookupError):
    def __init__(self, item_id: str) -> None:
        super().__init__(f"No item with id {item_id}")


class AnchorService:
    def __init__(self, unit_of_work: Callable[[], CatalogUnitOfWork]) -> None:
        self._unit_of_work = unit_of_work

    def set(self, project_id: str, start_item_id: str, end_item_id: str) -> Project:
        """Raises `ProjectNotFoundError`, `ItemNotFoundError` or `AnchorNotAPlaceError`; nothing changes."""
        with self._unit_of_work() as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise ProjectNotFoundError(project_id)
            start, end = (_found(uow.items.get(item_id), item_id) for item_id in (start_item_id, end_item_id))
            anchored = project.anchored(Anchors.chosen(project_id, start, end))
            uow.projects.update(anchored)
            uow.commit()
        return anchored


def _found(item: CatalogItem | None, item_id: str) -> CatalogItem:
    if item is None:
        raise ItemNotFoundError(item_id)
    return item

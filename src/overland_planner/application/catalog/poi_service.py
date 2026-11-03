"""POI use case (US-02c, brief §3, §5): add a named place by decimal degrees as an included item of a project.

The name and the coordinate ranges are checked before anything is opened, so a refusal adds nothing. One unit of
work adds the POI after the project's earlier items and increments the project revision once.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from overland_planner.application.catalog.project_service import ProjectNotFoundError
from overland_planner.application.ports.repositories import CatalogUnitOfWork
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.poi import PoiItem


class PoiService:
    def __init__(self, unit_of_work: Callable[[], CatalogUnitOfWork]) -> None:
        self._unit_of_work = unit_of_work

    def add(self, project_id: str, name: str, latitude: float, longitude: float) -> PoiItem:
        """Raises `PoiNameRequiredError`, `CoordinateOutOfRangeError` or `ProjectNotFoundError`; nothing is added."""
        poi = PoiItem.named(uuid.uuid4().hex, project_id, name, Coordinate(latitude, longitude))
        with self._unit_of_work() as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise ProjectNotFoundError(project_id)
            uow.items.add(poi)
            uow.projects.update(project.revised())
            uow.commit()
        return poi

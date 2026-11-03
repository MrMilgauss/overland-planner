"""HTTP request/response bodies (brief §5, D130): snake_case fields, ids as strings."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import ItemType, TrackItem
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


class PointResource(BaseModel):
    lat: float
    lon: float

    @classmethod
    def of(cls, coordinate: Coordinate) -> PointResource:
        return cls(lat=coordinate.latitude, lon=coordinate.longitude)


class ItemResource(BaseModel):
    """A catalog item (D107): `location` for a POI; `entry`, `exit` and `length_m` for a track; others null."""

    id: str
    type: ItemType
    name: str
    included: bool
    anchor: str | None
    location: PointResource | None
    entry: PointResource | None
    exit: PointResource | None
    length_m: float | None

    @classmethod
    def of(cls, item: TrackItem) -> ItemResource:
        return cls(
            id=item.id,
            type=item.type,
            name=item.name,
            included=item.included,
            anchor=item.anchor,
            location=None,
            entry=PointResource.of(item.entry),
            exit=PointResource.of(item.exit),
            length_m=item.length_m,
        )


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "not_found"},
    422: {"model": ErrorEnvelope, "description": "validation_error"},
}

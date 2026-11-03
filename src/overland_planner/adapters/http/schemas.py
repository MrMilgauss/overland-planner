"""HTTP request/response bodies (brief §5, D130): snake_case fields, ids as strings."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, ItemType, TrackItem
from overland_planner.domain.catalog.poi import AnchorRole
from overland_planner.domain.catalog.project import Project


class ErrorEnvelope(BaseModel):
    """Every non-2xx answer under /api (D183)."""

    code: str
    message: str


class ProjectCreate(BaseModel):
    name: str


class PoiCreate(BaseModel):
    """A place by decimal degrees. The ranges are the domain's rule (D151 reasons), so they are not checked here."""

    name: str
    lat: float
    lon: float


class AnchorsChoice(BaseModel):
    """The Start and End item ids (HC-2): POIs of the project, the same one for a round trip. Both required in 01a."""

    start_item_id: str
    end_item_id: str


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
    anchor: AnchorRole | None
    location: PointResource | None
    entry: PointResource | None
    exit: PointResource | None
    length_m: float | None

    @classmethod
    def of(cls, item: CatalogItem) -> ItemResource:
        if isinstance(item, TrackItem):
            entry, exit_ = PointResource.of(item.entry), PointResource.of(item.exit)
            return cls._with(item, entry=entry, exit=exit_, length_m=item.length_m)
        return cls._with(item, location=PointResource.of(item.location))

    @classmethod
    def _with(
        cls,
        item: CatalogItem,
        *,
        location: PointResource | None = None,
        entry: PointResource | None = None,
        exit: PointResource | None = None,
        length_m: float | None = None,
    ) -> ItemResource:
        """The fields every item has, plus the type-specific ones (null when the type has none)."""
        return cls(
            id=item.id,
            type=item.type,
            name=item.name,
            included=item.included,
            anchor=item.anchor,
            location=location,
            entry=entry,
            exit=exit,
            length_m=length_m,
        )


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "not_found"},
    422: {"model": ErrorEnvelope, "description": "validation_error"},
}

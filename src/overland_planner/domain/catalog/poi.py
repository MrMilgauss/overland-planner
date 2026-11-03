"""A place of interest (POI, US-02c): a named point added by decimal degrees, included by default. Pure domain.

Its name follows the project-name style rule: surrounding whitespace trimmed, never empty (refused with a reason).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from overland_planner.domain.catalog.coordinate import Coordinate


class PoiNameRequiredError(ValueError):
    """A POI name is empty once its surrounding whitespace is trimmed."""

    def __init__(self) -> None:
        super().__init__("Give the place a name")


@dataclass(frozen=True)
class PoiItem:
    """A POI of a project. `anchor` stays `None` until anchors arrive (03-09)."""

    id: str
    project_id: str
    name: str
    location: Coordinate
    included: bool = True
    anchor: str | None = None

    @classmethod
    def named(cls, poi_id: str, project_id: str, name: str, location: Coordinate) -> PoiItem:
        """Raises `PoiNameRequiredError` when the trimmed name is empty."""
        trimmed = name.strip()
        if not trimmed:
            raise PoiNameRequiredError()
        return cls(id=poi_id, project_id=project_id, name=trimmed, location=location)

    @property
    def type(self) -> Literal["poi"]:
        return "poi"

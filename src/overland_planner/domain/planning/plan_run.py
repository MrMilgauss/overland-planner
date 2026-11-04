"""A numbered plan run of a project (brief §8, §9). A job still running has no plan run. Pure domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem

PlanRunStatus = Literal["ready", "failed"]
StopKind = Literal["poi", "track"]


@dataclass(frozen=True)
class PlanRun:
    id: str
    number: int
    status: PlanRunStatus


@dataclass(frozen=True)
class PlanStop:
    """One stop of an itinerary. The first has no road leg; a POI holds `location`, a track the rest (HC-1)."""

    item_id: str
    name: str
    kind: StopKind
    leg_km: float | None
    location: Coordinate | None = None
    entry: Coordinate | None = None
    exit: Coordinate | None = None
    direction_version: int | None = None
    point_count: int | None = None
    canonical_sha256: str | None = None

    @classmethod
    def of(cls, item: CatalogItem, leg_km: float | None) -> PlanStop:
        if isinstance(item, TrackItem):
            return cls(
                item_id=item.id,
                name=item.name,
                kind="track",
                leg_km=leg_km,
                entry=item.entry,
                exit=item.exit,
                direction_version=item.direction_version,
                point_count=item.point_count,
                canonical_sha256=item.canonical_sha256,
            )
        return cls(item_id=item.id, name=item.name, kind="poi", leg_km=leg_km, location=item.location)

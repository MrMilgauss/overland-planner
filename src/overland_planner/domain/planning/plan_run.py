"""A numbered plan run of a project (brief §8, §9). A job still running has no plan run. Pure domain.

Km and seconds are kept as computed, not rounded: rounding for display is the web's. Sums use `math.fsum`, so the last
stop's cumulative values are exactly the totals whatever the order of the stops.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.project import DEFAULT_OFFROAD_SPEED, OffroadSpeed

PlanRunStatus = Literal["ready", "failed"]
StopKind = Literal["poi", "track"]
_METRES_PER_KM = 1000
_SECONDS_PER_HOUR = 3600


@dataclass(frozen=True)
class PlanRun:
    """`revision` is the project's revision the run was computed at; `stale` is decided on read, never stored."""

    id: str
    number: int
    status: PlanRunStatus
    revision: int
    stale: bool = False

    def seen_at(self, project_revision: int) -> PlanRun:
        """This run as listed while the project is at `project_revision`: Stale when that is not its own (brief §8)."""
        return replace(self, stale=self.revision != project_revision)


@dataclass(frozen=True)
class PlanStop:
    """One stop of an itinerary (FR-6.1). The first has no road leg; a POI holds `location`, a track the rest (HC-1).

    `leg_km`/`leg_s` is the road into the stop; a track's `track_km`/`offroad_s` is its stored length driven at the
    project's off-road speed (FR-4.6); `cumulative_km`/`cumulative_s` is road plus off-road to the stop's end (D11).
    """

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
    leg_s: int | None = None
    track_km: float | None = None
    offroad_s: float | None = None
    cumulative_km: float = 0.0
    cumulative_s: float = 0.0

    @classmethod
    def of(cls, item: CatalogItem, leg_km: float | None) -> PlanStop:
        """Where and how the item is reached, without what is driven."""
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

    @classmethod
    def driving(
        cls, item: CatalogItem, leg: tuple[float, int] | None, offroad_speed: OffroadSpeed = DEFAULT_OFFROAD_SPEED
    ) -> PlanStop:
        """`of` the item with its road leg (km, s) and, for a track, its length and off-road time (FR-4.6)."""
        leg_km, leg_s = (None, None) if leg is None else leg
        stop = replace(cls.of(item, leg_km), leg_s=leg_s)
        if not isinstance(item, TrackItem):
            return stop
        track_km = stored_length_km(item)
        return replace(stop, track_km=track_km, offroad_s=track_km / offroad_speed.kmh * _SECONDS_PER_HOUR)

    def driven_km(self) -> tuple[float, float]:
        """Road and off-road km driven to reach and through this stop."""
        return self.leg_km or 0.0, self.track_km or 0.0

    def driven_s(self) -> tuple[float, float]:
        return self.leg_s or 0, self.offroad_s or 0.0

    def ending(self, driven_before: Sequence[PlanStop]) -> PlanStop:
        """This stop with its cumulative values, after the stops `driven_before` it."""
        stops = (*driven_before, self)
        return replace(self, cumulative_km=_driven_km(stops), cumulative_s=_driven_s(stops))


@dataclass(frozen=True)
class Totals:
    """The six totals of a plan (FR-6.2): road, off-road and their sum, in km and in seconds. Compared by value."""

    road_km: float = 0.0
    road_s: int = 0
    offroad_km: float = 0.0
    offroad_s: float = 0.0
    total_km: float = 0.0
    total_s: float = 0.0

    @classmethod
    def of(cls, stops: Sequence[PlanStop]) -> Totals:
        return cls(
            road_km=math.fsum(stop.driven_km()[0] for stop in stops),
            road_s=sum(stop.leg_s or 0 for stop in stops),
            offroad_km=math.fsum(stop.driven_km()[1] for stop in stops),
            offroad_s=math.fsum(stop.driven_s()[1] for stop in stops),
            total_km=_driven_km(stops),
            total_s=_driven_s(stops),
        )


def stored_length_km(track: TrackItem) -> float:
    """The track's stored length, the off-road km a stop of it drives (HC-5, ADR-009 check 4)."""
    return track.length_m / _METRES_PER_KM


def _driven_km(stops: Iterable[PlanStop]) -> float:
    return math.fsum(km for stop in stops for km in stop.driven_km())


def _driven_s(stops: Iterable[PlanStop]) -> float:
    return math.fsum(s for stop in stops for s in stop.driven_s())

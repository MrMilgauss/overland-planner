"""Road legs between points and the table of a plan's legs (brief section 8). Pure domain.

A leg carries its road distance in integer metres, as the leg cache holds them, and its road time in seconds. Nothing
is driven between identical points, so that leg is 0 m and 0 s and needs no row. A pair that is missing otherwise is a
programming error and raises `KeyError`.

A road map answers each pair at a level (brief section 6): `confirmed`, or `unconfirmed` with the reason it is not; a
pair with no road at any level has no measure at all (`None` in the port's matrix). A pair with an end the road map
cannot snap to a road is answered `OffNetwork`, which names that end or those ends: for the table it is a pair with no
road. The table keeps that answer apart from a pair nobody asked: the measure of a pair with no road raises
`NoRoadError`, a pair nobody asked `KeyError`; `connected` says whether any road joins a pair (identical points do:
0 m, nothing to drive).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from overland_planner.domain.catalog.coordinate import Coordinate

RoadPair = tuple[Coordinate, Coordinate]
RoadLevel = Literal["confirmed", "unconfirmed"]
_METRES_PER_KM = 1000


@dataclass(frozen=True)
class RoadMeasure:
    """What the road map answers for one pair: road distance in metres, road time in seconds, its level and reason."""

    distance_m: int
    duration_s: int
    level: RoadLevel = "confirmed"
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.level == "confirmed" and self.reason is None:
            return
        if self.level == "unconfirmed" and self.reason is not None and self.reason.strip():
            return
        raise ValueError(f"a {self.level} road measure cannot carry the reason {self.reason!r}")


@dataclass(frozen=True)
class OffNetwork:
    """What the road map answers for a pair when it cannot snap an end of it to a road open to vehicles: the end or
    ends of the pair it names."""

    places: frozenset[Coordinate]

    def __post_init__(self) -> None:
        if not self.places:
            raise ValueError("an off-network answer names at least one place")


NOTHING_TO_DRIVE = RoadMeasure(distance_m=0, duration_s=0)


class NoRoadError(LookupError):
    """The pair was asked and the road map has no road for it at any level, so it has no distance or time."""


@dataclass(frozen=True)
class RoadLeg:
    origin: Coordinate
    destination: Coordinate
    distance_m: int
    duration_s: int
    level: RoadLevel = "confirmed"
    reason: str | None = None


class LegTable:
    def __init__(self, legs: Iterable[RoadLeg], no_road: Iterable[RoadPair] = ()) -> None:
        self._measures: dict[RoadPair, RoadMeasure | None] = {
            (leg.origin, leg.destination): RoadMeasure(leg.distance_m, leg.duration_s, leg.level, leg.reason)
            for leg in legs
        }
        self._measures.update(dict.fromkeys(no_road))

    def level(self, origin: Coordinate, destination: Coordinate) -> RoadLevel:
        return self._measure(origin, destination).level

    def reason(self, origin: Coordinate, destination: Coordinate) -> str | None:
        return self._measure(origin, destination).reason

    def connected(self, origin: Coordinate, destination: Coordinate) -> bool:
        """Whether a road at any level joins the pair; `KeyError` for a pair nobody asked."""
        return origin == destination or self._measures[origin, destination] is not None

    def merged_with(self, later: LegTable) -> LegTable:
        """A table that answers what either did; for a pair both answered, the later table's answer."""
        merged = LegTable([])
        merged._measures = {**self._measures, **later._measures}
        return merged

    def distance_m(self, origin: Coordinate, destination: Coordinate) -> int:
        return self._measure(origin, destination).distance_m

    def duration_s(self, origin: Coordinate, destination: Coordinate) -> int:
        return self._measure(origin, destination).duration_s

    def distance_km(self, origin: Coordinate, destination: Coordinate) -> float:
        return self.distance_m(origin, destination) / _METRES_PER_KM

    def km_and_s(self, origin: Coordinate, destination: Coordinate) -> tuple[float, int]:
        """The leg as a plan stop carries it: road distance in km and road time in seconds."""
        return self.distance_km(origin, destination), self.duration_s(origin, destination)

    def _measure(self, origin: Coordinate, destination: Coordinate) -> RoadMeasure:
        if origin == destination:
            return NOTHING_TO_DRIVE
        measure = self._measures[origin, destination]
        if measure is None:
            raise NoRoadError(f"the road map has no road from {origin} to {destination} at any level")
        return measure

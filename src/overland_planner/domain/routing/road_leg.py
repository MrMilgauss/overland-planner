"""Road legs between points and the table of a plan's legs (brief section 8). Pure domain.

A leg carries its road distance in integer metres, as the leg cache holds them, and its road time in seconds. Nothing
is driven between identical points, so that leg is 0 m and 0 s and needs no row. A pair that is missing otherwise is a
programming error and raises `KeyError`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from overland_planner.domain.catalog.coordinate import Coordinate

RoadPair = tuple[Coordinate, Coordinate]
_METRES_PER_KM = 1000


@dataclass(frozen=True)
class RoadMeasure:
    """What the road map answers for one pair: road distance in metres and road time in seconds."""

    distance_m: int
    duration_s: int


NOTHING_TO_DRIVE = RoadMeasure(distance_m=0, duration_s=0)


@dataclass(frozen=True)
class RoadLeg:
    origin: Coordinate
    destination: Coordinate
    distance_m: int
    duration_s: int


class LegTable:
    def __init__(self, legs: Iterable[RoadLeg]) -> None:
        self._measures = {(leg.origin, leg.destination): RoadMeasure(leg.distance_m, leg.duration_s) for leg in legs}

    def distance_m(self, origin: Coordinate, destination: Coordinate) -> int:
        return self._measure(origin, destination).distance_m

    def duration_s(self, origin: Coordinate, destination: Coordinate) -> int:
        return self._measure(origin, destination).duration_s

    def distance_km(self, origin: Coordinate, destination: Coordinate) -> float:
        return self.distance_m(origin, destination) / _METRES_PER_KM

    def _measure(self, origin: Coordinate, destination: Coordinate) -> RoadMeasure:
        if origin == destination:
            return NOTHING_TO_DRIVE
        return self._measures[origin, destination]

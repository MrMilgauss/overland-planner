"""Road legs between points and the table of a plan's legs (brief section 8). Pure domain.

Distances are integer metres, as the leg cache holds them. Nothing is driven between identical points, so that leg is
0 m and needs no row. A pair that is missing otherwise is a programming error and raises `KeyError`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from overland_planner.domain.catalog.coordinate import Coordinate

RoadPair = tuple[Coordinate, Coordinate]


@dataclass(frozen=True)
class RoadLeg:
    origin: Coordinate
    destination: Coordinate
    distance_m: int


class LegTable:
    def __init__(self, legs: Iterable[RoadLeg]) -> None:
        self._distance_m = {(leg.origin, leg.destination): leg.distance_m for leg in legs}

    def distance_m(self, origin: Coordinate, destination: Coordinate) -> int:
        if origin == destination:
            return 0
        return self._distance_m[origin, destination]

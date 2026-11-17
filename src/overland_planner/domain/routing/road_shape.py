"""The shape of the road between two points (ADR-007 Amendment 2, D252). Pure domain.

`points` run from the origin to the destination; `available` is false when the road map has no road there, in which
case the points are the straight line between the two places, drawn as such. Identical points have one point.
"""

from __future__ import annotations

from dataclasses import dataclass

from overland_planner.domain.catalog.coordinate import Coordinate


@dataclass(frozen=True)
class RoadShape:
    points: tuple[Coordinate, ...]
    available: bool

    @classmethod
    def straight_line(cls, origin: Coordinate, destination: Coordinate, *, available: bool = True) -> RoadShape:
        """The straight line between two places; a single point when they are the same."""
        points = (origin,) if origin == destination else (origin, destination)
        return cls(points, available)

"""Track statistics (brief §4, US-02a): length, entry and exit, in recorded order (HC-1). Pure domain.

Length is the sum of the great-circle lengths of consecutive segments. Points are never reordered: entry is the
first recorded point and exit the last. A track of fewer than two points has no statistics.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from overland_planner.domain.catalog.track import TrackPoint

MINIMUM_POINTS = 2


@dataclass(frozen=True)
class TrackStats:
    """Statistics of a usable track."""

    length_m: float
    entry: TrackPoint
    exit: TrackPoint


@dataclass(frozen=True)
class UnusableTrack:
    """A track that cannot be used, and why."""

    point_count: int
    reason: str = "A track needs at least two points"


class TrackStatsCalculator:
    """Computes the statistics of a recorded track without reordering its points."""

    def calculate(self, points: Sequence[TrackPoint]) -> TrackStats | UnusableTrack:
        if len(points) < MINIMUM_POINTS:
            return UnusableTrack(len(points))
        length_m = sum(a.coordinate.great_circle_distance_m(b.coordinate) for a, b in pairwise(points))
        return TrackStats(length_m=length_m, entry=points[0], exit=points[-1])

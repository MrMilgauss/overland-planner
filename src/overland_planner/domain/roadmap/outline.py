"""A region's land outline: rings with holes, even-odd containment, the boundary counts as inside (D302).

Longitude is x, latitude is y, on the flat lon/lat plane (the Geofabrik outlines are lon/lat polygons; the antimeridian
is out of scope). Outlines hold a few thousand points, so containment is plain ray casting with no spatial index.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from itertools import pairwise

from overland_planner.domain.catalog.coordinate import Coordinate

Ring = tuple[Coordinate, ...]
Segment = tuple[Coordinate, Coordinate]


def _segments(ring: Ring) -> list[Segment]:
    """The ring's edges, closing edge included (a repeated first point adds only a zero-length edge)."""
    return [*pairwise(ring), (ring[-1], ring[0])]


def _cross(o: Coordinate, a: Coordinate, b: Coordinate) -> float:
    return (a.longitude - o.longitude) * (b.latitude - o.latitude) - (a.latitude - o.latitude) * (
        b.longitude - o.longitude
    )


def _within_box(p: Coordinate, a: Coordinate, b: Coordinate) -> bool:
    return min(a.longitude, b.longitude) <= p.longitude <= max(a.longitude, b.longitude) and min(
        a.latitude, b.latitude
    ) <= p.latitude <= max(a.latitude, b.latitude)


def _on_segment(p: Coordinate, segment: Segment) -> bool:
    a, b = segment
    return _cross(a, b, p) == 0 and _within_box(p, a, b)


def _segments_meet(s: Segment, t: Segment) -> bool:
    a, b = s
    c, d = t
    d1, d2 = _cross(a, b, c), _cross(a, b, d)
    d3, d4 = _cross(c, d, a), _cross(c, d, b)
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return True
    return _on_segment(c, s) or _on_segment(d, s) or _on_segment(a, t) or _on_segment(b, t)


Bounds = tuple[float, float, float, float]  # south, west, north, east


def _overlap(a: Bounds, b: Bounds) -> Bounds | None:
    south, west, north, east = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return None if south > north or west > east else (south, west, north, east)


def _in_bounds(p: Coordinate, box: Bounds) -> bool:
    return box[0] <= p.latitude <= box[2] and box[1] <= p.longitude <= box[3]


def _bounds_of(s: Segment) -> Bounds:
    a, b = s
    return (
        min(a.latitude, b.latitude),
        min(a.longitude, b.longitude),
        max(a.latitude, b.latitude),
        max(a.longitude, b.longitude),
    )


def _segment_in(s: Segment, box: Bounds) -> bool:
    return _overlap(_bounds_of(s), box) is not None


def _boxes_meet(s: Segment, t: Segment) -> bool:
    return _overlap(_bounds_of(s), _bounds_of(t)) is not None


def _crosses_ray(p: Coordinate, segment: Segment) -> bool:
    """Whether the segment crosses the ray going east from p (half-open on latitude, so a vertex counts once)."""
    a, b = segment
    if (a.latitude > p.latitude) == (b.latitude > p.latitude):
        return False
    lon_at_p = a.longitude + (p.latitude - a.latitude) * (b.longitude - a.longitude) / (b.latitude - a.latitude)
    return p.longitude < lon_at_p


@dataclass(frozen=True)
class Outline:
    """Outer rings plus holes; a point is inside when it lies on an edge or crosses an odd number of edges."""

    rings: tuple[Ring, ...]
    holes: tuple[Ring, ...] = ()

    @cached_property
    def _all_segments(self) -> list[Segment]:
        return [s for ring in (*self.rings, *self.holes) for s in _segments(ring)]

    @cached_property
    def _bounds(self) -> Bounds:
        """South, west, north, east of the outer rings (holes lie inside them)."""
        points = [p for ring in self.rings for p in ring]
        lats, lons = [p.latitude for p in points], [p.longitude for p in points]
        return min(lats), min(lons), max(lats), max(lons)

    @cached_property
    def _boundary_segments(self) -> list[Segment]:
        return [s for ring in self.rings for s in _segments(ring)]

    def contains(self, point: Coordinate) -> bool:
        segments = self._all_segments
        if any(_on_segment(point, s) for s in segments):
            return True
        return sum(_crosses_ray(point, s) for s in segments) % 2 == 1

    def touches(self, other: Outline) -> bool:
        """Whether the two outlines overlap or touch: a vertex of one inside the other, or edges meeting."""
        box = _overlap(self._bounds, other._bounds)
        if box is None:  # far apart: nothing of one can meet or lie in the other
            return False
        mine = [s for s in self._boundary_segments if _segment_in(s, box)]
        theirs = [t for t in other._boundary_segments if _segment_in(t, box)]
        if any(_boxes_meet(s, t) and _segments_meet(s, t) for s in mine for t in theirs):
            return True
        return any(_in_bounds(s[0], other._bounds) and other.contains(s[0]) for s in mine) or any(
            _in_bounds(t[0], self._bounds) and self.contains(t[0]) for t in theirs
        )

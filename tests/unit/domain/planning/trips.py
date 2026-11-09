"""Generated trips for the planning domain tests: a project snapshot and a road leg table, shared by the two test files.

Points come from a small pool so that different items often share a point. Every ordered pair of different points has
its own distance, so an arc or a leg taken from the wrong end of a track shows up. Pairs of identical points are left
out of the table on purpose: no router answers them. Track lengths and the project's off-road speed are drawn too, the
default 15 km/h among them.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise, permutations

from hypothesis import strategies as st

from overland_planner.application.catalog.facade import canonical_points_file
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.catalog.project import DEFAULT_OFFROAD_SPEED, OffroadSpeed
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.planning.plan_run import Totals
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg
from tests.common.catalog_fakes import InMemoryFileStore

PROJECT = "p"
POINTS = tuple(Coordinate(45.0 + i / 10, 7.0 + i / 10) for i in range(5))
POINT_PAIRS = tuple(permutations(POINTS, 2))
NAMES = ("Casa Marco", "Briancon", "Strada dell'Assietta")  # few on purpose: names may repeat, item ids do not

points = st.sampled_from(POINTS)
names = st.sampled_from(NAMES)
track_lengths_m = st.floats(min_value=1.0, max_value=200_000.0, allow_nan=False, allow_infinity=False)
offroad_speeds = st.one_of(st.just(DEFAULT_OFFROAD_SPEED), st.floats(0.5, 120.0).map(OffroadSpeed))


@dataclass(frozen=True)
class Trip:
    snapshot: ProjectSnapshot
    legs: LegTable
    leg_m: dict[tuple[Coordinate, Coordinate], int]
    start: CatalogItem
    end: CatalogItem
    items: tuple[CatalogItem, ...]

    def road_m(self, origin: Coordinate, destination: Coordinate) -> int:
        """The road between two points: nothing to drive between identical points."""
        return 0 if origin == destination else self.leg_m[origin, destination]

    def road_s(self, origin: Coordinate, destination: Coordinate) -> int:
        """The road time between two points, as the leg table was given it."""
        return 0 if origin == destination else road_time_s(self.leg_m[origin, destination])

    @property
    def speed(self) -> OffroadSpeed:
        return self.snapshot.offroad_speed

    def tracks(self) -> tuple[TrackItem, ...]:
        """The Included tracks to place, the ones a plan must drive."""
        return tuple(item for item in self.items if isinstance(item, TrackItem))

    def seed_canonical_files(self, store: InMemoryFileStore) -> None:
        """The canonical points files as the import wrote them, for every track of the project."""
        for item in self.snapshot.items:
            if isinstance(item, TrackItem):
                store.keep_canonical_points(item.id, item.direction_version, canonical_file_of(item))


def reached_at(item: CatalogItem) -> Coordinate:
    return item.entry if isinstance(item, TrackItem) else item.location


def left_at(item: CatalogItem) -> Coordinate:
    return item.exit if isinstance(item, TrackItem) else item.location


def road_time_s(distance_m: int) -> int:
    """A made-up road time, about 72 km/h, never 0 for a road that is driven."""
    return max(1, distance_m * 3 // 50)


def leg_table(leg_m: dict[tuple[Coordinate, Coordinate], int]) -> LegTable:
    """The road legs of these distances, each driven in its `road_time_s`."""
    return LegTable(RoadLeg(origin, destination, m, road_time_s(m)) for (origin, destination), m in leg_m.items())


def track_points(entry: Coordinate, exit_: Coordinate, point_count: int) -> tuple[TrackPoint, ...]:
    """A recorded sequence from entry to exit; the points between are made up, their identity is all that matters."""
    between = (TrackPoint.at(45.9, 7.9 + i / 1000, 1000.0 + i) for i in range(point_count - 2))
    return (TrackPoint(entry), *between, TrackPoint(exit_))


def planned_totals(
    snapshot: ProjectSnapshot, leg_m: dict[tuple[Coordinate, Coordinate], int], visited: Sequence[str]
) -> Totals:
    """The six totals of driving Start, `visited` and End, from the leg distances and the track lengths alone (FR-6.2):
    each road leg from where a stop is left to where the next is reached, each track at the project's speed (FR-4.6).
    """
    stops = (snapshot.start(), *map(snapshot.item, visited), snapshot.end())
    roads = [(left_at(previous), reached_at(item)) for previous, item in pairwise(stops)]
    driven = [(0, 0) if a == b else (leg_m[a, b], road_time_s(leg_m[a, b])) for a, b in roads]  # nothing at one point
    road_km, road_s = [m / 1000 for m, _ in driven], [s for _, s in driven]
    track_km = [item.length_m / 1000 for item in stops if isinstance(item, TrackItem)]
    offroad_s = [km / snapshot.offroad_speed.kmh * 3600 for km in track_km]
    return Totals(
        road_km=math.fsum(road_km),
        road_s=sum(road_s),
        offroad_km=math.fsum(track_km),
        offroad_s=math.fsum(offroad_s),
        total_km=math.fsum(road_km + track_km),
        total_s=math.fsum([*road_s, *offroad_s]),
    )


def canonical_file_of(track: TrackItem) -> bytes:
    return canonical_points_file(track_points(track.entry, track.exit, track.point_count))


def _poi(draw: st.DrawFn, item_id: str, included: bool = True) -> PoiItem:
    return PoiItem(id=item_id, project_id=PROJECT, name=draw(names), location=draw(points), included=included)


def _track(draw: st.DrawFn, item_id: str, included: bool = True) -> TrackItem:
    entry, exit_, point_count = draw(points), draw(points), draw(st.integers(2, 20))
    canonical = canonical_points_file(track_points(entry, exit_, point_count))
    return TrackItem(
        id=item_id,
        project_id=PROJECT,
        name=draw(names),
        description=None,
        original_sha256="original",
        canonical_sha256=hashlib.sha256(canonical).hexdigest(),
        direction_version=draw(st.integers(1, 9)),
        point_count=point_count,
        entry=entry,
        exit=exit_,
        length_m=draw(track_lengths_m),
        included=included,
    )


def _item(draw: st.DrawFn, item_id: str, included: bool = True) -> CatalogItem:
    make = draw(st.sampled_from((_poi, _track)))
    return make(draw, item_id, included)


@st.composite
def trips(draw: st.DrawFn) -> Trip:
    """A one-way or round trip with k >= 0 Included items and some Excluded ones, listed in any order."""
    start = _poi(draw, "start")
    end = start if draw(st.booleans()) else _poi(draw, "end")
    items = tuple(_item(draw, f"item-{i}") for i in range(draw(st.integers(0, 6))))
    excluded = tuple(_item(draw, f"excluded-{i}", included=False) for i in range(draw(st.integers(0, 2))))
    listed = draw(st.permutations(list({item.id: item for item in (start, end, *items, *excluded)}.values())))
    distances = draw(
        st.lists(st.integers(1, 400_000), min_size=len(POINT_PAIRS), max_size=len(POINT_PAIRS), unique=True)
    )
    leg_m = dict(zip(POINT_PAIRS, distances, strict=True))
    snapshot = ProjectSnapshot(start.id, end.id, tuple(listed), draw(offroad_speeds))
    return Trip(snapshot, leg_table(leg_m), leg_m, start, end, items)

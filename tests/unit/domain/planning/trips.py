"""Generated trips for the planning domain tests: a project snapshot and a road leg table, shared by the two test files.

Points come from a small pool so that different items often share a point. Every ordered pair of different points has
its own distance, so an arc or a leg taken from the wrong end of a track shows up. Pairs of identical points are left
out of the table on purpose: no router answers them.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg

PROJECT = "p"
POINTS = tuple(Coordinate(45.0 + i / 10, 7.0 + i / 10) for i in range(5))
POINT_PAIRS = tuple(permutations(POINTS, 2))
NAMES = ("Casa Marco", "Briancon", "Strada dell'Assietta")  # few on purpose: names may repeat, item ids do not

points = st.sampled_from(POINTS)
names = st.sampled_from(NAMES)


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


def reached_at(item: CatalogItem) -> Coordinate:
    return item.entry if isinstance(item, TrackItem) else item.location


def left_at(item: CatalogItem) -> Coordinate:
    return item.exit if isinstance(item, TrackItem) else item.location


def _poi(draw: st.DrawFn, item_id: str, included: bool = True) -> PoiItem:
    return PoiItem(id=item_id, project_id=PROJECT, name=draw(names), location=draw(points), included=included)


def _track(draw: st.DrawFn, item_id: str, included: bool = True) -> TrackItem:
    return TrackItem(
        id=item_id,
        project_id=PROJECT,
        name=draw(names),
        description=None,
        original_sha256="original",
        canonical_sha256=f"sha-{item_id}",
        direction_version=draw(st.integers(1, 9)),
        point_count=draw(st.integers(2, 5000)),
        entry=draw(points),
        exit=draw(points),
        length_m=1000.0,
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
    legs = LegTable(RoadLeg(origin, destination, m) for (origin, destination), m in leg_m.items())
    return Trip(ProjectSnapshot(start.id, end.id, tuple(listed)), legs, leg_m, start, end, items)

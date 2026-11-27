"""CoverageService through its driving port `of()`; the served map and the project's items are the two inputs (D302).

Universe: the answer (known, map_date, region names, outside item ids, groups). Two square regions, one far from the
other, stand for the served borders; a trail is outside by its entry or its exit, never by its middle (the item does
not even keep one).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import ProjectNotFoundError
from overland_planner.application.roadmap.coverage_service import CoverageService, TripCoverage
from overland_planner.application.roadmap.service import ServedMapView
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.roadmap.coverage import RoadMapCoverage
from overland_planner.domain.roadmap.outline import Outline

DATE = datetime(2026, 11, 27, 12, tzinfo=UTC)


def square(south: float, west: float) -> Outline:
    ring = (
        Coordinate(south, west),
        Coordinate(south, west + 10),
        Coordinate(south + 10, west + 10),
        Coordinate(south + 10, west),
    )
    return Outline(rings=(ring,))


HOME, FAR = square(0, 0), square(50, 50)  # 0..10 and 50..60, in degrees, on both axes
KNOWN = ServedMapView(
    known=True,
    map_date=DATE,
    regions=(),
    total_bytes=0,
    coverage=RoadMapCoverage((("Home", HOME), ("Far", FAR))),
)
UNKNOWN = ServedMapView(known=False, map_date=DATE, regions=(), total_bytes=0)


def place(item_id: str, lat: float, lon: float, included: bool = True) -> PoiItem:
    return PoiItem(item_id, "p", item_id, Coordinate(lat, lon), included=included)


def trail(item_id: str, entry: tuple[float, float], exit: tuple[float, float], included: bool = True) -> TrackItem:
    return TrackItem(item_id, "p", item_id, None, "o", "c", 1, 2, Coordinate(*entry), Coordinate(*exit), 1.0, included)


def coverage_of(served: ServedMapView, *items: CatalogItem) -> TripCoverage:
    return CoverageService(lambda _id: items, lambda: served).of("p")


def test_a_place_is_outside_by_its_point_and_the_map_names_its_regions_and_date() -> None:
    answer = coverage_of(KNOWN, place("in", 5, 5), place("out", 30, 30))
    assert (answer.known, answer.map_date, answer.regions) == (True, DATE, ("Far", "Home"))
    assert answer.outside_item_ids == ("out",)


@given(
    entry=st.tuples(st.integers(-5, 65), st.integers(-5, 65)),
    exit=st.tuples(st.integers(-5, 65), st.integers(-5, 65)),
)
def test_a_trail_is_outside_when_its_entry_or_its_exit_is(entry: tuple[int, int], exit: tuple[int, int]) -> None:
    def inside(point: tuple[int, int]) -> bool:
        return all(0 < c < 10 or 50 < c < 60 for c in point)

    if any(c in (0, 10, 50, 60) for c in (*entry, *exit)):
        return  # a point on a border is the domain's business (outline.py), not the trip rule
    answer = coverage_of(KNOWN, trail("t", entry, exit))
    assert (answer.outside_item_ids == ("t",)) == (not inside(entry) or not inside(exit))


def test_an_excluded_item_is_never_listed_nor_grouped() -> None:
    answer = coverage_of(KNOWN, place("out", 30, 30, included=False), place("in", 5, 5, included=False))
    assert answer.outside_item_ids == () and answer.groups == ()


def test_an_unknown_map_judges_nothing_and_keeps_its_date() -> None:
    answer = coverage_of(UNKNOWN, place("out", 30, 30), trail("t", (30, 30), (5, 5)))
    assert answer == TripCoverage(known=False, map_date=DATE, regions=(), outside_item_ids=(), groups=())


def test_stops_in_regions_not_linked_by_land_fall_in_two_groups_named_with_their_stops() -> None:
    answer = coverage_of(KNOWN, place("a", 5, 5), trail("t", (55, 55), (5, 5)), place("out", 30, 30))
    assert [(g.regions, g.item_ids) for g in answer.groups] == [(("Far",), ("t",)), (("Home",), ("a", "t"))]


def test_an_unknown_project_is_not_found() -> None:
    def refuse(project_id: str) -> list[CatalogItem]:
        raise ProjectNotFoundError(project_id)

    with pytest.raises(ProjectNotFoundError):
        CoverageService(refuse, lambda: KNOWN).of("nope")

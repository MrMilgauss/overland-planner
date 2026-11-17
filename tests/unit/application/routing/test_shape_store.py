"""The shape store (ADR-007 Amendment 2, D252): road shapes kept in memory per road map, profile and pair.

Driving port: `ShapeStore` from the routing facade. Driven port: `RoutingProvider`, here the offline road map behind a
spy that counts the shapes asked. Observable universe: `road_map.shapes_asked`, the pairs asked with their counts, and
`answers`, the shapes the store handed back.
Test Budget: 2 behaviors (an available shape is asked of the road map once per road map, profile and pair, whoever
asks again; a shape that is not available is never kept, so it is asked again) x 2 = 4; 2 used.
"""

from __future__ import annotations

from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.adapters.routing.mock_routing_provider import MockRoutingProvider
from overland_planner.application.routing.facade import RoadMapKey, ShapeStore
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_shape import RoadShape
from tests.common.state_delta import assert_state_delta, set_to

points = st.builds(
    Coordinate, st.floats(44.0, 46.0, allow_nan=False).map(lambda v: round(v, 5)), st.just(7.0) | st.just(7.5)
)
pairs = st.lists(st.tuples(points, points), min_size=1, max_size=8)
UNIVERSE = {"road_map.shapes_asked", "answers"}


class _SpyRoadMap(MockRoutingProvider):
    """The offline road map that counts the shapes asked and can answer them all as not available."""

    def __init__(self, *, available: bool) -> None:
        super().__init__()
        self._available = available
        self.shapes_asked: Counter[tuple[Coordinate, Coordinate]] = Counter()

    def route_shape(self, origin: Coordinate, destination: Coordinate) -> RoadShape:
        self.shapes_asked[origin, destination] += 1
        shape = super().route_shape(origin, destination)
        return shape if self._available else RoadShape(shape.points, available=False)


def _ask_all(store: ShapeStore, wanted: list[tuple[Coordinate, Coordinate]], road_map: RoadMapKey) -> list[RoadShape]:
    return [store.shape(origin, destination, road_map=road_map) for origin, destination in wanted]


@given(wanted=pairs)
@settings(max_examples=60, deadline=None)
def test_an_available_shape_is_asked_once_per_road_map_and_pair(wanted: list[tuple[Coordinate, Coordinate]]) -> None:
    spy = _SpyRoadMap(available=True)
    store = ShapeStore(spy)
    here: RoadMapKey = ("road-map-a", "profile-1")
    elsewhere: RoadMapKey = ("road-map-b", "profile-1")
    first = _ask_all(store, wanted, here)
    before = {"road_map.shapes_asked": Counter(spy.shapes_asked), "answers": first}

    again = _ask_all(store, wanted, here) + _ask_all(store, wanted, elsewhere)
    after = {"road_map.shapes_asked": Counter(spy.shapes_asked), "answers": first}

    assert again == first * 2 and all(shape.available for shape in again)
    distinct = set(wanted)
    assert_state_delta(
        before,
        after,
        UNIVERSE,
        {"road_map.shapes_asked": set_to(Counter({pair: 2 for pair in distinct}))},
        strict=True,
    )
    assert before["road_map.shapes_asked"] == Counter({pair: 1 for pair in distinct})


@given(wanted=pairs)
@settings(max_examples=40, deadline=None)
def test_a_shape_that_is_not_available_is_never_kept(wanted: list[tuple[Coordinate, Coordinate]]) -> None:
    spy = _SpyRoadMap(available=False)
    store = ShapeStore(spy)
    road_map: RoadMapKey = ("road-map-a", "profile-1")

    answers = _ask_all(store, wanted, road_map) + _ask_all(store, wanted, road_map)

    assert not any(shape.available for shape in answers)
    assert spy.shapes_asked == Counter({pair: 2 * wanted.count(pair) for pair in set(wanted)})

"""The legs of a plan (brief section 8): what the leg resolver asks the road map for, and the table it hands back.

Driving port: `LegResolver` from the routing facade, with the required pairs of the real `SolverModelBuilder`. Driven
port: `RoutingProvider` (recording double). Observable universe: `road_map.asked`, the pairs asked with their counts.
Test Budget: 1 behavior (the required legs come from the road map, each distinct pair asked once) x 2 = 2; 1 used.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from hypothesis import given

from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.application.planning.planning_doubles import RecordingRoadMap
from tests.unit.domain.planning.trips import Trip, trips

UNIVERSE = {"road_map.asked"}


def _view(road_map: RecordingRoadMap) -> dict[str, Any]:
    return {"road_map.asked": Counter(road_map.asked)}


@given(trip=trips())
def test_each_distinct_required_pair_is_asked_exactly_once_and_the_table_covers_them_all(trip: Trip) -> None:
    pairs = SolverModelBuilder(trip.snapshot).required_pairs()
    road_map = RecordingRoadMap(trip.leg_m)
    before = _view(road_map)

    table = LegResolver(road_map).resolve(pairs)

    distinct_roads = Counter(pair for pair in set(pairs) if pair[0] != pair[1])
    assert_state_delta(before, _view(road_map), UNIVERSE, {"road_map.asked": set_to(distinct_roads)}, strict=True)
    assert [table.distance_m(*pair) for pair in pairs] == [trip.road_m(*pair) for pair in pairs]

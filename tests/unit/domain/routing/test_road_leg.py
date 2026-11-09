"""A plan's road legs (brief section 8): each carries its distance and its road time, identical points need neither.

Driving port: `LegTable` (`distance_m`, `distance_km`, `duration_s`). Observable universe: what the table answers for
the pairs it was given (`legs.distance_m`, `legs.duration_s`) and for a point and itself (`legs.identical_points`).
Test Budget: 2 behaviors (a leg answers its own distance and road time, identical points 0 m and 0 s; metres read as
kilometres) x 2 = 4; 2 used.
"""

from __future__ import annotations

from itertools import permutations
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg, RoadPair
from tests.common.state_delta import assert_state_delta, set_to

TORINO = Coordinate(45.0703, 7.6869)
BRIANCON = Coordinate(44.8986, 6.6419)
UNIVERSE = {"legs.distance_m", "legs.duration_s", "legs.identical_points"}

alpine_points = st.builds(
    Coordinate,
    st.floats(44.0, 46.5).map(lambda lat: round(lat, 6)),
    st.floats(6.5, 8.5).map(lambda lon: round(lon, 6)),
)


@st.composite
def legs_between(draw: st.DrawFn) -> tuple[list[Coordinate], dict[RoadPair, tuple[int, int]]]:
    points = draw(st.lists(alpine_points, min_size=2, max_size=5, unique=True))
    pairs = list(permutations(points, 2))
    measures = draw(st.lists(st.tuples(st.integers(1, 900_000), st.integers(1, 60_000)), min_size=len(pairs)))
    return points, dict(zip(pairs, measures, strict=False))


def _view(table: LegTable | None, points: list[Coordinate], pairs: list[RoadPair]) -> dict[str, Any]:
    if table is None:
        return {slot: None for slot in UNIVERSE}
    return {
        "legs.distance_m": {pair: table.distance_m(*pair) for pair in pairs},
        "legs.duration_s": {pair: table.duration_s(*pair) for pair in pairs},
        "legs.identical_points": {
            point: (table.distance_m(point, point), table.duration_s(point, point)) for point in points
        },
    }


@given(case=legs_between())
def test_each_leg_answers_its_own_distance_and_road_time_and_identical_points_answer_zero(
    case: tuple[list[Coordinate], dict[RoadPair, tuple[int, int]]],
) -> None:
    points, measures = case
    pairs = list(measures)
    before = _view(None, points, pairs)

    table = LegTable(RoadLeg(origin, destination, m, s) for (origin, destination), (m, s) in measures.items())

    assert_state_delta(
        before,
        _view(table, points, pairs),
        UNIVERSE,
        {
            "legs.distance_m": set_to({pair: m for pair, (m, _) in measures.items()}),
            "legs.duration_s": set_to({pair: s for pair, (_, s) in measures.items()}),
            "legs.identical_points": set_to(dict.fromkeys(points, (0, 0))),
        },
        strict=True,
    )


# bypass: no property - a generated expectation would repeat the formula; these literals are worked out by hand.
@pytest.mark.parametrize(
    ("metres", "origin", "destination", "kilometres"),
    [(1500, TORINO, BRIANCON, 1.5), (0, TORINO, BRIANCON, 0.0), (1500, TORINO, TORINO, 0.0)],
    ids=["1500-m", "a-leg-of-0-m", "identical-points"],
)
def test_a_leg_reads_in_kilometres(metres: int, origin: Coordinate, destination: Coordinate, kilometres: float) -> None:
    legs = LegTable([RoadLeg(TORINO, BRIANCON, metres, 90)])

    assert legs.distance_km(origin, destination) == kilometres

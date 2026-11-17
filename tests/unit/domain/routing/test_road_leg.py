"""A plan's road legs (brief section 8): each carries its distance and its road time, identical points need neither.

Driving port: `LegTable` (`distance_m`, `distance_km`, `duration_s`). Observable universe: what the table answers for
the pairs it was given (`legs.distance_m`, `legs.duration_s`) and for a point and itself (`legs.identical_points`).
Test Budget: 2 behaviors (a leg answers its own distance and road time, identical points 0 m and 0 s; metres read as
kilometres; a road measure carries a level and the reason of an unconfirmed one) x 2 = 6; 3 used.
"""

from __future__ import annotations

from itertools import permutations
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import LegTable, NoRoadError, OffNetwork, RoadLeg, RoadMeasure, RoadPair
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


def _measured(level: str | None, reason: str | None) -> Any:
    kwargs = {} if level is None else {"level": level}
    kwargs |= {} if reason is None else {"reason": reason}
    try:
        measure = RoadMeasure(1200, 90, **kwargs)
    except ValueError:
        return "refused"
    return (measure.level, measure.reason)


@given(
    level=st.one_of(st.none(), st.sampled_from(["confirmed", "unconfirmed", "none", "Confirmed", ""])),
    reason=st.one_of(st.none(), st.just(""), st.text(alphabet="abc_ ", min_size=1)),
)
def test_a_measure_is_confirmed_by_default_and_an_unconfirmed_one_always_says_why(
    level: str | None, reason: str | None
) -> None:
    before = {"measure.outcome": None}

    valid_unconfirmed = level == "unconfirmed" and bool(reason and reason.strip())
    valid_confirmed = level in (None, "confirmed") and reason is None
    expected = (
        (level or "confirmed", reason) if valid_unconfirmed or valid_confirmed else "refused"
    )  # oracle: the two rules of brief section 6, not the class's own checks

    assert_state_delta(
        before,
        {"measure.outcome": _measured(level, reason)},
        {"measure.outcome"},
        {"measure.outcome": set_to(expected)},
        strict=True,
    )


# ----------------------------------------------------------------------- level, reason and no road (07-03, ADR-017)
KNOWN_UNIVERSE = {"legs.answers", "legs.identical_points", "legs.unasked", "legs.no_road_measure"}
ANSWERS = ("confirmed", "unconfirmed", "no_road")


@st.composite
def answered_pairs(draw: st.DrawFn) -> tuple[list[Coordinate], dict[RoadPair, str]]:
    """Every ordered pair of a few points, each answered confirmed, unconfirmed (with a reason) or with no road."""
    points = draw(st.lists(alpine_points, min_size=2, max_size=4, unique=True))
    pairs = list(permutations(points, 2))
    return points, dict(zip(pairs, draw(st.lists(st.sampled_from(ANSWERS), min_size=len(pairs))), strict=False))


def _table_of(answers: dict[RoadPair, str]) -> LegTable:
    legs = [
        RoadLeg(*pair, 1200, 90, *(("confirmed", None) if kind == "confirmed" else ("unconfirmed", f"why {i}")))
        for i, (pair, kind) in enumerate(answers.items())
        if kind != "no_road"
    ]
    return LegTable(legs, no_road=[pair for pair, kind in answers.items() if kind == "no_road"])


def _known_view(table: LegTable | None, points: list[Coordinate], answers: dict[RoadPair, str]) -> dict[str, Any]:
    if table is None:
        return {slot: None for slot in KNOWN_UNIVERSE}
    far = Coordinate(10.0, 10.0)  # a point nobody asked about
    return {
        "legs.answers": {
            pair: (table.level(*pair), table.reason(*pair), table.connected(*pair))
            if kind != "no_road"
            else (None, None, table.connected(*pair))
            for pair, kind in answers.items()
        },
        "legs.identical_points": {p: (table.level(p, p), table.reason(p, p), table.connected(p, p)) for p in points},
        "legs.unasked": _raises(KeyError, lambda: table.connected(points[0], far)),
        "legs.no_road_measure": {
            pair: _raises(NoRoadError, lambda pair=pair: table.distance_m(*pair))
            for pair, kind in answers.items()
            if kind == "no_road"
        },
    }


def _raises(error: type[Exception], ask: Any) -> bool:
    try:
        ask()
    except error:
        return True
    return False


@given(case=answered_pairs())
def test_a_table_answers_each_pairs_level_and_reason_and_whether_a_road_connects_it_and_tells_no_road_from_unasked(
    case: tuple[list[Coordinate], dict[RoadPair, str]],
) -> None:
    points, answers = case
    before = _known_view(None, points, answers)

    table = _table_of(answers)

    reasons = {pair: f"why {i}" for i, pair in enumerate(answers)}
    assert_state_delta(
        before,
        _known_view(table, points, answers),
        KNOWN_UNIVERSE,
        {
            "legs.answers": set_to(
                {
                    pair: (None, None, False)
                    if kind == "no_road"
                    else (kind, None if kind == "confirmed" else reasons[pair], True)
                    for pair, kind in answers.items()
                }
            ),
            "legs.identical_points": set_to(dict.fromkeys(points, ("confirmed", None, True))),
            "legs.unasked": set_to(True),
            "legs.no_road_measure": set_to({pair: True for pair, kind in answers.items() if kind == "no_road"}),
        },
        strict=True,
    )


@given(left=answered_pairs(), right=answered_pairs())
def test_two_tables_merge_into_one_that_answers_what_either_did_the_later_one_first(
    left: tuple[list[Coordinate], dict[RoadPair, str]], right: tuple[list[Coordinate], dict[RoadPair, str]]
) -> None:
    (_, asked_left), (_, asked_right) = left, right
    before = {"merged.connected": None}

    merged = _table_of(asked_left).merged_with(_table_of(asked_right))

    expected = {pair: kind != "no_road" for pair, kind in {**asked_left, **asked_right}.items()}
    assert_state_delta(
        before,
        {"merged.connected": {pair: merged.connected(*pair) for pair in expected}},
        {"merged.connected"},
        {"merged.connected": set_to(expected)},
        strict=True,
    )


@given(places=st.frozensets(st.builds(Coordinate, st.floats(-90, 90), st.floats(-180, 180)), min_size=1, max_size=2))
def test_an_off_network_answer_names_its_places_and_cannot_name_none(
    places: frozenset[Coordinate],
) -> None:
    assert OffNetwork(places).places == places
    with pytest.raises(ValueError):
        OffNetwork(frozenset())

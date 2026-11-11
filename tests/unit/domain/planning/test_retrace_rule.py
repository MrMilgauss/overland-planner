"""The retrace rule (ADR-017 section 2, one definition for the model, the assembler and the guard). Pure domain.

Driving port: `arc_kind(previous, successor, legs)` and `second_pass_pair(previous, successor, legs)`.
Observable universe: `rule.arc_kind`, `rule.second_pass_pair`, and `legs.connected` (the table is only read).
Test Budget: 2 behaviors (what the arc t -> j is: road, retrace or forbidden; which second pair the job must ask)
x 2 = 4; 2 used. The oracle is a truth table over three facts, not the rule's own branches.
"""

from __future__ import annotations

from itertools import permutations
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.planning.retrace_rule import arc_kind, second_pass_pair
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg, RoadPair
from tests.common.state_delta import assert_state_delta, set_to, unchanged

POINTS = tuple(Coordinate(45.0 + i / 10, 7.0 + i / 10) for i in range(4))
POINT_PAIRS = tuple(permutations(POINTS, 2))
UNIVERSE = {"rule.arc_kind", "rule.second_pass_pair", "legs.connected"}

# (the road leaves the exit, the item can be retraced, the road leaves the entry) -> the arc
TRUTH_TABLE = {
    (True, True, True): "road",
    (True, True, False): "road",
    (True, False, True): "road",
    (True, False, False): "road",
    (False, True, True): "retrace",
    (False, True, False): "forbidden",
    (False, False, True): "forbidden",
    (False, False, False): "forbidden",
}
points = st.sampled_from(POINTS)


@st.composite
def items(draw: st.DrawFn) -> CatalogItem:
    if draw(st.booleans()):
        return PoiItem(id="poi", project_id="p", name="Casa", location=draw(points))
    entry, exit_ = draw(points), draw(points)  # a loop track when they are the same point
    return TrackItem("track", "p", "Pass", None, "o", "c", 1, 2, entry, exit_, 1000.0)


@st.composite
def tables(draw: st.DrawFn) -> LegTable:
    """Every pair of different points answered: a road at a random level, or no road."""
    kinds = draw(st.lists(st.sampled_from(("confirmed", "unconfirmed", "no_road")), min_size=len(POINT_PAIRS)))
    legs = [
        RoadLeg(*pair, 1, 1, *(("confirmed", None) if kind == "confirmed" else ("unconfirmed", "not on the map")))
        for pair, kind in zip(POINT_PAIRS, kinds, strict=False)
        if kind != "no_road"
    ]
    return LegTable(legs, no_road=[pair for pair, kind in zip(POINT_PAIRS, kinds, strict=False) if kind == "no_road"])


def _entry(item: CatalogItem) -> Coordinate:
    return item.entry if isinstance(item, TrackItem) else item.location


def _exit(item: CatalogItem) -> Coordinate:
    return item.exit if isinstance(item, TrackItem) else item.location


def _view(legs: LegTable, verdict: Any = None, pair: Any = None) -> dict[str, Any]:
    connected = {p: legs.connected(*p) for p in POINT_PAIRS}
    return {"rule.arc_kind": verdict, "rule.second_pass_pair": pair, "legs.connected": connected}


@given(previous=items(), successor=items(), legs=tables())
def test_an_arc_is_a_road_when_one_leaves_the_exit_a_retrace_only_for_a_track_with_a_road_from_its_entry_else_forbidden(
    previous: CatalogItem, successor: CatalogItem, legs: LegTable
) -> None:
    before = _view(legs)

    verdict = arc_kind(previous, successor, legs)
    pair = second_pass_pair(previous, successor, legs)

    leaves_exit = legs.connected(_exit(previous), _entry(successor))  # identical points are connected: nothing to drive
    retraceable = isinstance(previous, TrackItem) and previous.entry != previous.exit
    leaves_entry = legs.connected(_entry(previous), _entry(successor))
    expected_kind = TRUTH_TABLE[leaves_exit, retraceable, leaves_entry]
    expected_pair: RoadPair | None = (_entry(previous), _entry(successor)) if retraceable and not leaves_exit else None
    assert_state_delta(
        before,
        _view(legs, verdict, pair),
        UNIVERSE,
        {
            "rule.arc_kind": set_to(expected_kind),
            "rule.second_pass_pair": set_to(expected_pair),
            "legs.connected": unchanged(),
        },
        strict=True,
    )

"""Assembling a plan (US-02b, HC-1, HC-2): a chosen order becomes ordered stops with their road legs in km.

Driving port: `PlanRunAssembler` (`assemble(order)` is its public interface).
Observable universe = the stops as the itinerary, the guard and the export read them, and the snapshot read.
Test Budget: 2 behaviors (stops in order with their details, road leg of each stop) x 2 = 4; 2 used.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.planning.plan_run_assembler import PlanRunAssembler
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.domain.planning.trips import Trip, left_at, reached_at, trips


@st.composite
def planned_trips(draw: st.DrawFn) -> tuple[Trip, tuple[CatalogItem, ...]]:
    """A trip and any order of its Included items."""
    trip = draw(trips())
    return trip, tuple(draw(st.permutations(trip.items)))


def _row(stop: PlanStop) -> tuple[Any, ...]:
    return (
        stop.item_id,
        stop.name,
        stop.kind,
        stop.location,
        stop.entry,
        stop.exit,
        stop.direction_version,
        stop.point_count,
        stop.canonical_sha256,
    )


def _expected_row(item: CatalogItem) -> tuple[Any, ...]:
    if isinstance(item, TrackItem):
        return (
            item.id,
            item.name,
            "track",
            None,
            item.entry,
            item.exit,
            item.direction_version,
            item.point_count,
            item.canonical_sha256,
        )
    return (item.id, item.name, "poi", item.location, None, None, None, None, None)


def _assembled(trip: Trip, order: tuple[CatalogItem, ...], universe: set[str]) -> dict[str, Any]:
    stops = PlanRunAssembler(trip.snapshot, trip.legs).assemble([item.id for item in order])
    observed = {
        "snapshot.read": trip.snapshot,
        "plan.stops": tuple(_row(stop) for stop in stops),
        "plan.leg_km": tuple(stop.leg_km for stop in stops),
    }
    return {slot: observed[slot] for slot in universe}


@given(planned=planned_trips())
def test_assembled_plan_keeps_start_first_end_last_each_item_once(
    planned: tuple[Trip, tuple[CatalogItem, ...]],
) -> None:
    trip, order = planned
    universe = {"snapshot.read", "plan.stops"}
    before = {"snapshot.read": trip.snapshot, "plan.stops": ()}

    after = _assembled(trip, order, universe)

    stops = tuple(_expected_row(item) for item in (trip.start, *order, trip.end))
    assert_state_delta(before, after, universe, {"plan.stops": set_to(stops)}, strict=True)


@given(planned=planned_trips())
def test_leg_km_follows_the_leg_table(planned: tuple[Trip, tuple[CatalogItem, ...]]) -> None:
    trip, order = planned
    universe = {"snapshot.read", "plan.leg_km"}
    before = {"snapshot.read": trip.snapshot, "plan.leg_km": ()}

    after = _assembled(trip, order, universe)

    roads = [
        trip.road_m(left_at(one), reached_at(other)) / 1000 for one, other in pairwise((trip.start, *order, trip.end))
    ]
    assert_state_delta(before, after, universe, {"plan.leg_km": set_to((None, *roads))}, strict=True)

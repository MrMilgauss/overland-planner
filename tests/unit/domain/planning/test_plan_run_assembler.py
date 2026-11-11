"""Assembling a plan (US-02b, US-05, HC-1, HC-2, FR-6.1, FR-6.2, D11): a chosen order becomes ordered stops with
their road legs, track lengths, off-road times and cumulative values, and the plan's six totals.

Driving ports: `PlanRunAssembler` (`assemble(order)`) and `Totals.of(stops)`, both pure.
Observable universe = the stops as the itinerary, the guard and the export read them, the totals and the snapshot read.
Test Budget: 8 behaviors (stops in order with their details, road leg of each stop, what each stop drives, cumulative
to the end of each stop, the totals, the report of a run's outcome, the retrace row after a dead-end track, the level
of each road leg) x 2 = 16; 9 used.
Km and seconds are not rounded by the domain; expected values are worked out here from the business rules (km from
metres, off-road time = length / speed) and compared within float rounding, the last cumulative against the totals
exactly.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.ports.tour_solver import TourNoRoute, TourOptimizerFailed, TourTimedOut
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.planning.invariant_guard import INVARIANT_VIOLATION_REASON
from overland_planner.domain.planning.plan_run import PlanReport, PlanStop, Totals
from overland_planner.domain.planning.plan_run_assembler import PlanRunAssembler
from overland_planner.domain.routing.road_leg import LegTable
from tests.common.predicates import close_to
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.domain.planning.retrace_trips import RETRACE_REASON, Pair, level_of, levelled_dead_end_trips
from tests.unit.domain.planning.trips import PRODUCT_WORDS, Trip, left_at, reached_at, trips


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


def _totals_row(totals: Totals) -> tuple[Any, ...]:
    return (totals.road_km, totals.road_s, totals.offroad_km, totals.offroad_s, totals.total_km, totals.total_s)


def _assembled(trip: Trip, order: tuple[CatalogItem, ...], universe: set[str]) -> dict[str, Any]:
    stops = PlanRunAssembler(trip.snapshot, trip.legs).assemble([item.id for item in order])
    observed = {
        "snapshot.read": trip.snapshot,
        "plan.stops": tuple(_row(stop) for stop in stops),
        "plan.leg_km": tuple(stop.leg_km for stop in stops),
        "plan.driving": tuple((stop.leg_s, stop.track_km, stop.offroad_s) for stop in stops),
        "plan.cumulative": tuple((stop.cumulative_km, stop.cumulative_s) for stop in stops),
        "plan.totals": _totals_row(Totals.of(stops)),
        "plan.last_cumulative_is_total": (stops[-1].cumulative_km, stops[-1].cumulative_s)
        == (Totals.of(stops).total_km, Totals.of(stops).total_s),
    }
    return {slot: observed[slot] for slot in universe}


def _trip_of(trip: Trip, order: tuple[CatalogItem, ...]) -> tuple[CatalogItem, ...]:
    return (trip.start, *order, trip.end)


def _road_legs(trip: Trip, order: tuple[CatalogItem, ...]) -> list[tuple[float, int]]:
    """Each leg as (km, s), from where a stop is left to where the next is reached."""
    return [
        (trip.road_m(left_at(one), reached_at(other)) / 1000, trip.road_s(left_at(one), reached_at(other)))
        for one, other in pairwise(_trip_of(trip, order))
    ]


def _offroad(trip: Trip, item: CatalogItem) -> tuple[float, float] | None:
    """A track as (km, s): its stored length driven at the project's off-road speed (FR-4.6)."""
    if not isinstance(item, TrackItem):
        return None
    km = item.length_m / 1000
    return km, km / trip.speed.kmh * 3600


def _driven(trip: Trip, order: tuple[CatalogItem, ...]) -> Sequence[tuple[float, float]]:
    """What is driven to reach and through each stop, in (km, s): the road leg into it plus its track (D11)."""
    legs = [(0.0, 0), *_road_legs(trip, order)]
    driven = []
    for (leg_km, leg_s), item in zip(legs, _trip_of(trip, order), strict=True):
        track_km, track_s = _offroad(trip, item) or (0.0, 0.0)
        driven.append((leg_km + track_km, leg_s + track_s))
    return driven


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


@given(planned=planned_trips())
def test_each_stop_carries_its_leg_time_and_a_track_its_length_and_offroad_time(
    planned: tuple[Trip, tuple[CatalogItem, ...]],
) -> None:
    trip, order = planned
    universe = {"snapshot.read", "plan.driving"}
    before = {"snapshot.read": trip.snapshot, "plan.driving": ()}

    after = _assembled(trip, order, universe)

    leg_times = (None, *(leg_s for _, leg_s in _road_legs(trip, order)))
    offroad = (_offroad(trip, item) or (None, None) for item in _trip_of(trip, order))
    driving = tuple((leg_s, *track) for leg_s, track in zip(leg_times, offroad, strict=True))
    assert_state_delta(before, after, universe, {"plan.driving": close_to(driving)}, strict=True)


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@given(planned=planned_trips())
def test_cumulative_km_and_time_run_to_the_end_of_each_stop(planned: tuple[Trip, tuple[CatalogItem, ...]]) -> None:
    trip, order = planned
    universe = {"snapshot.read", "plan.cumulative"}
    before = {"snapshot.read": trip.snapshot, "plan.cumulative": ()}

    after = _assembled(trip, order, universe)

    driven = _driven(trip, order)
    cumulative = tuple(
        (math.fsum(km for km, _ in driven[: at + 1]), math.fsum(s for _, s in driven[: at + 1]))
        for at in range(len(driven))
    )
    assert_state_delta(before, after, universe, {"plan.cumulative": close_to(cumulative)}, strict=True)
    for (km, s), (next_km, next_s) in pairwise(after["plan.cumulative"]):
        assert next_km >= km and next_s >= s, f"the cumulative goes back: {after['plan.cumulative']}"


@given(planned=planned_trips())
def test_totals_sum_the_road_legs_and_the_tracks_and_end_the_cumulative(
    planned: tuple[Trip, tuple[CatalogItem, ...]],
) -> None:
    trip, order = planned
    universe = {"snapshot.read", "plan.totals", "plan.last_cumulative_is_total"}
    before = {"snapshot.read": trip.snapshot, "plan.totals": (), "plan.last_cumulative_is_total": False}

    after = _assembled(trip, order, universe)

    legs = _road_legs(trip, order)
    tracks = [track for track in (_offroad(trip, item) for item in order) if track is not None]
    road_km, road_s = math.fsum(km for km, _ in legs), sum(s for _, s in legs)
    offroad_km, offroad_s = math.fsum(km for km, _ in tracks), math.fsum(s for _, s in tracks)
    totals = (road_km, road_s, offroad_km, offroad_s, road_km + offroad_km, road_s + offroad_s)
    expected = {"plan.totals": close_to(totals), "plan.last_cumulative_is_total": set_to(True)}
    assert_state_delta(before, after, universe, expected, strict=True)
    if not order:
        assert (len(legs), after["plan.totals"][2:4]) == (1, (0, 0)), "Start and End only: one leg, no off-road"


_NO_LEG = (None, None, None, None)


def _oracle(trip: Trip, order: tuple[CatalogItem, ...], no_road: set[Pair], unconfirmed: set[Pair]) -> list[Any]:
    """The expected stops as (kind, item id, name, leg, retrace) worked out from the rules, not from the assembler:
    a track whose exit has no road to the next stop is followed by its retrace, and the road goes on from its entry."""
    sequence = _trip_of(trip, order)
    expected: list[Any] = [("poi", sequence[0].id, sequence[0].name, _NO_LEG, None)]
    for previous, item in pairwise(sequence):
        origin = left_at(previous)
        if (origin, reached_at(item)) in no_road:
            assert isinstance(previous, TrackItem)
            expected.append(("retrace", previous.id, f"Retrace {previous.name}", _NO_LEG, previous))
            origin = previous.entry
        pair = (origin, reached_at(item))
        level, reason = level_of(pair, unconfirmed)
        leg = (trip.road_m(*pair) / 1000, trip.road_s(*pair), level, reason)
        expected.append(("track" if isinstance(item, TrackItem) else "poi", item.id, item.name, leg, None))
    return expected


@given(dead_ends=levelled_dead_end_trips(), data=st.data())
def test_a_dead_end_track_is_followed_by_its_retrace_and_the_road_goes_on_from_its_entry(
    dead_ends: tuple[Trip, LegTable, set[Pair], set[Pair]], data: st.DataObject
) -> None:
    trip, legs, no_road, unconfirmed = dead_ends
    order = tuple(data.draw(st.permutations(trip.items)))
    stops = PlanRunAssembler(trip.snapshot, legs).assemble([item.id for item in order])
    universe = {"snapshot.read", "plan.rows", "plan.retraces", "plan.road_legs", "plan.totals"}
    before = {
        "snapshot.read": trip.snapshot,
        "plan.rows": (),
        "plan.retraces": (),
        "plan.road_legs": (),
        "plan.totals": (),
    }

    after = {
        "snapshot.read": trip.snapshot,
        "plan.rows": tuple((stop.kind, stop.item_id, stop.name) for stop in stops),
        "plan.retraces": tuple(
            (s.entry, s.exit, s.confidence, s.reason, s.track_km, s.offroad_s, s.leg_km, s.leg_s, s.leg_confidence)
            for s in stops
            if s.kind == "retrace"
        ),
        "plan.road_legs": tuple((s.leg_km, s.leg_s, s.leg_confidence, s.leg_reason) for s in stops),
        "plan.totals": _totals_row(Totals.of(stops)),
    }

    expected = _oracle(trip, order, no_road, unconfirmed)
    retraced = [track for *_, track in expected if track is not None]
    retrace_km = [track.length_m / 1000 for track in retraced]
    retrace_s = [km / trip.speed.kmh * 3600 for km in retrace_km]
    expected_retraces = tuple(
        (t.exit, t.entry, "unconfirmed", RETRACE_REASON, km, s, None, None, None)
        for t, km, s in zip(retraced, retrace_km, retrace_s, strict=True)
    )
    legs_km = [leg[0] for *_, leg, _ in expected if leg[0] is not None]
    legs_s = [leg[1] for *_, leg, _ in expected if leg[1] is not None]
    tracks = [item for item in _trip_of(trip, order) if isinstance(item, TrackItem)]
    track_km = [t.length_m / 1000 for t in tracks]
    track_s = [km / trip.speed.kmh * 3600 for km in track_km]
    offroad_km, offroad_s = math.fsum([*track_km, *retrace_km]), math.fsum([*track_s, *retrace_s])
    totals = (
        math.fsum(legs_km),
        sum(legs_s),
        offroad_km,
        offroad_s,
        math.fsum(legs_km) + offroad_km,
        sum(legs_s) + offroad_s,
    )
    assert_state_delta(
        before,
        after,
        universe,
        {
            "plan.rows": set_to(tuple((kind, item_id, name) for kind, item_id, name, *_ in expected)),
            "plan.retraces": close_to(expected_retraces),
            "plan.road_legs": close_to(tuple(leg for *_, leg, _ in expected)),
            "plan.totals": close_to(totals),
        },
        strict=True,
    )
    assert (stops[-1].cumulative_km, stops[-1].cumulative_s) == (Totals.of(stops).total_km, Totals.of(stops).total_s)


STORED_CODES = {TourNoRoute.reason, TourOptimizerFailed.reason, TourTimedOut.reason, INVARIANT_VIOLATION_REASON}
unknown_codes = (
    st.lists(st.from_regex(r"[a-z]{1,8}", fullmatch=True), min_size=1, max_size=4)
    .map("_".join)
    .filter(lambda code: code not in PRODUCT_WORDS)
)


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@given(planned=planned_trips(), unknown=unknown_codes, data=st.data())
def test_a_failed_run_reports_its_reason_in_product_words_and_a_ready_run_has_no_report(
    planned: tuple[Trip, tuple[CatalogItem, ...]], unknown: str, data: st.DataObject
) -> None:
    """Every code a run can store, one with no wording (its words, D220 e) and the ready outcome (`None`) on every
    example (D212), in any order."""
    assert set(PRODUCT_WORDS) == STORED_CODES, "every reason a solver outcome or the guard can store has its words"
    codes = data.draw(st.permutations([*PRODUCT_WORDS, unknown, None]), label="codes")
    trip, _ = planned
    assembler = PlanRunAssembler(trip.snapshot, trip.legs)
    universe = {"snapshot.read", "plan.reports"}
    before = {"snapshot.read": trip.snapshot, "plan.reports": {}}

    after = {"snapshot.read": trip.snapshot, "plan.reports": {code: assembler.report(code) for code in codes}}

    words = {**PRODUCT_WORDS, unknown: " ".join(unknown.split("_"))}
    reports = {code: None if code is None else PlanReport(reason=words[code]) for code in codes}
    assert_state_delta(before, after, universe, {"plan.reports": set_to(reports)}, strict=True)

"""The HC guard on a plan (ADR-009 with Amendments 1 and 2, slice 01b scope plus slice 02's track length and leg time):
every assembled plan passes, every broken one fails naming its rule.

Driving port: `InvariantGuard` (`check_order`, `check_plan` are its public interface; it is pure).
Observable universe = the guard's result, the stops it judged and the snapshot read.
Test Budget: 3 behaviors (assembled plans pass, a broken plan names its rule, a broken chosen order names its rule)
x 2 = 6; 3 used.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from hypothesis import given, note
from hypothesis import strategies as st

from overland_planner.domain.catalog.item import TrackItem
from overland_planner.domain.planning.invariant_guard import (
    CanonicalFileEvidence,
    GuardViolation,
    InvariantGuard,
)
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.planning.plan_run_assembler import PlanRunAssembler
from overland_planner.domain.routing.road_leg import LegTable
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.domain.planning.trips import POINTS, Trip, trips

UNIVERSE = {"guard.check", "plan.stops", "snapshot.read"}
Files = Mapping[str, CanonicalFileEvidence]


@dataclass(frozen=True)
class Plan:
    trip: Trip
    stops: tuple[PlanStop, ...]
    files: Files

    def guard(self) -> InvariantGuard:
        return InvariantGuard(self.trip.snapshot, self.trip.legs)

    @property
    def later_positions(self) -> range:
        """The positions of the stops between the anchors."""
        return range(1, len(self.stops) - 1)

    def track_positions(self) -> list[int]:
        return [at for at, stop in enumerate(self.stops) if stop.kind == "track"]

    def poi_positions(self) -> list[int]:
        return [at for at, stop in enumerate(self.stops) if stop.kind == "poi"]

    def with_stop(self, at: int, **changes: Any) -> tuple[PlanStop, ...]:
        return (*self.stops[:at], replace(self.stops[at], **changes), *self.stops[at + 1 :])

    def inserted(self, at: int, stop: PlanStop) -> tuple[PlanStop, ...]:
        return (*self.stops[:at], stop, *self.stops[at:])


def _evidence_of(track: TrackItem) -> CanonicalFileEvidence:
    return CanonicalFileEvidence(track.canonical_sha256, track.point_count, track.entry, track.exit)


@st.composite
def plans(draw: st.DrawFn) -> Plan:
    """A trip, any order of its Included items, the plan the assembler makes of it and the files as imported."""
    trip = draw(trips())
    order = draw(st.permutations(trip.items))
    stops = PlanRunAssembler(trip.snapshot, trip.legs).assemble([item.id for item in order])
    return Plan(trip, stops, {track.id: _evidence_of(track) for track in trip.tracks()})


def _judged(plan: Plan, stops: tuple[PlanStop, ...], violation: GuardViolation | None) -> dict[str, Any]:
    check = None if violation is None else violation.check
    return {"guard.check": check, "plan.stops": stops, "snapshot.read": plan.trip.snapshot}


@dataclass(frozen=True)
class Broken:
    """A broken plan: its stops, its files, the rule it breaks and the item the detail must name (if it is one item)."""

    stops: tuple[PlanStop, ...]
    files: Files
    rule: str
    item_id: str | None = None
    legs: LegTable | None = None


Breaking = Callable[[Plan, st.DrawFn], Broken]


def _swap(stops: tuple[PlanStop, ...], one: int, other: int) -> tuple[PlanStop, ...]:
    swapped = list(stops)
    swapped[one], swapped[other] = swapped[other], swapped[one]
    return tuple(swapped)


def _first_stop_swapped_with_the_next(plan: Plan, _: st.DrawFn) -> Broken:
    return Broken(_swap(plan.stops, 0, 1), plan.files, "HC-2")


def _last_stop_swapped_with_the_previous(plan: Plan, _: st.DrawFn) -> Broken:
    return Broken(_swap(plan.stops, -1, -2), plan.files, "HC-2")


def _first_stop_dropped(plan: Plan, _: st.DrawFn) -> Broken:
    return Broken(plan.stops[1:], plan.files, "HC-2")


def _last_stop_dropped(plan: Plan, _: st.DrawFn) -> Broken:
    return Broken(plan.stops[:-1], plan.files, "HC-2")


def _no_stops(plan: Plan, _: st.DrawFn) -> Broken:
    return Broken((), plan.files, "HC-2")


def _anchor_shown_as_a_track(plan: Plan, draw: st.DrawFn) -> Broken:
    at = draw(st.sampled_from((0, len(plan.stops) - 1)))
    return Broken(plan.with_stop(at, kind="track"), plan.files, "HC-2")


def _item_dropped(plan: Plan, draw: st.DrawFn) -> Broken:
    at = draw(st.sampled_from(plan.later_positions))
    return Broken((*plan.stops[:at], *plan.stops[at + 1 :]), plan.files, "HC-3", plan.stops[at].item_id)


def _item_repeated(plan: Plan, draw: st.DrawFn) -> Broken:
    at = draw(st.sampled_from(plan.later_positions))
    return Broken(plan.inserted(at, plan.stops[at]), plan.files, "HC-3", plan.stops[at].item_id)


def _anchor_repeated_between(plan: Plan, _: st.DrawFn) -> Broken:
    return Broken(plan.inserted(1, plan.stops[0]), plan.files, "HC-3", plan.stops[0].item_id)


def _unknown_item_added(plan: Plan, _: st.DrawFn) -> Broken:
    return Broken(plan.inserted(1, replace(plan.stops[0], item_id="no-such-item")), plan.files, "HC-3", "no-such-item")


def _excluded_item_added(plan: Plan, _: st.DrawFn) -> Broken:
    excluded = next(item for item in plan.trip.snapshot.items if not item.included)
    return Broken(plan.inserted(1, PlanStop.of(excluded, 1.0)), plan.files, "HC-3", excluded.id)


def _entry_and_exit_swapped(plan: Plan, draw: st.DrawFn) -> Broken:
    at = draw(st.sampled_from([at for at in plan.track_positions() if plan.stops[at].entry != plan.stops[at].exit]))
    stop = plan.stops[at]
    return Broken(plan.with_stop(at, entry=stop.exit, exit=stop.entry), plan.files, "HC-1", stop.item_id)


def _other_direction_version(plan: Plan, draw: st.DrawFn) -> Broken:
    at = draw(st.sampled_from(plan.track_positions()))
    stop = plan.stops[at]
    assert stop.direction_version is not None
    return Broken(plan.with_stop(at, direction_version=stop.direction_version + 1), plan.files, "HC-1", stop.item_id)


def _place_moved(plan: Plan, draw: st.DrawFn) -> Broken:
    at = draw(st.sampled_from(plan.poi_positions()))
    stop = plan.stops[at]
    moved = draw(st.sampled_from([point for point in POINTS if point != stop.location]))
    return Broken(plan.with_stop(at, location=moved), plan.files, "HC-1", stop.item_id)


def _stop_shows_other_point_count(plan: Plan, draw: st.DrawFn) -> Broken:
    at = draw(st.sampled_from(plan.track_positions()))
    stop = plan.stops[at]
    assert stop.point_count is not None
    return Broken(plan.with_stop(at, point_count=stop.point_count + 1), plan.files, "HC-5", stop.item_id)


def _stop_shows_other_hash(plan: Plan, draw: st.DrawFn) -> Broken:
    at = draw(st.sampled_from(plan.track_positions()))
    stop = plan.stops[at]
    return Broken(plan.with_stop(at, canonical_sha256="other"), plan.files, "HC-5", stop.item_id)


def _file_vanished(plan: Plan, draw: st.DrawFn) -> Broken:
    gone = draw(st.sampled_from(sorted(plan.files)))
    return Broken(plan.stops, {k: v for k, v in plan.files.items() if k != gone}, "HC-5", gone)


def _file_differs(plan: Plan, draw: st.DrawFn) -> Broken:
    """Each part of the evidence on its own: a mid-sequence edit shows only in the hash."""
    track = draw(st.sampled_from(sorted(plan.files)))
    evidence = plan.files[track]
    elsewhere = draw(st.sampled_from([point for point in POINTS if point not in (evidence.first, evidence.last)]))
    changed = draw(
        st.sampled_from(
            (
                replace(evidence, sha256="other"),
                replace(evidence, point_count=evidence.point_count + 1),
                replace(evidence, first=elsewhere),
                replace(evidence, last=elsewhere),
            )
        )
    )
    return Broken(plan.stops, {**plan.files, track: changed}, "HC-5", track)


def _road_leg_differs(plan: Plan, draw: st.DrawFn) -> Broken:
    at = draw(st.integers(1, len(plan.stops) - 1))
    stop = plan.stops[at]
    assert stop.leg_km is not None
    return Broken(plan.with_stop(at, leg_km=stop.leg_km + 0.001), plan.files, "leg_consistency", stop.item_id)


def _first_stop_has_a_road_leg(plan: Plan, _: st.DrawFn) -> Broken:
    return Broken(plan.with_stop(0, leg_km=0.0), plan.files, "leg_consistency", plan.stops[0].item_id)


def _track_length_differs(plan: Plan, draw: st.DrawFn) -> Broken:
    """ADR-009 check 4, its length part: the stop drives other than the stored length, or no length at all."""
    at = draw(st.sampled_from(plan.track_positions()))
    stop = plan.stops[at]
    assert stop.track_km is not None
    length = draw(st.sampled_from((stop.track_km + 0.001, stop.track_km / 2, None)))
    return Broken(plan.with_stop(at, track_km=length), plan.files, "HC-5", stop.item_id)


def _leg_time_differs(plan: Plan, draw: st.DrawFn) -> Broken:
    """ADR-009 check 5, its time part: the distance is the table's, the time is not."""
    at = draw(st.integers(1, len(plan.stops) - 1))
    stop = plan.stops[at]
    assert stop.leg_s is not None
    leg_s = draw(st.sampled_from((stop.leg_s + 1, None)))
    return Broken(plan.with_stop(at, leg_s=leg_s), plan.files, "leg_consistency", stop.item_id)


def _first_stop_has_a_leg_time(plan: Plan, _: st.DrawFn) -> Broken:
    return Broken(plan.with_stop(0, leg_s=0), plan.files, "leg_consistency", plan.stops[0].item_id)


def _road_leg_nobody_measured(plan: Plan, _: st.DrawFn) -> Broken:
    """A snapshot whose leg table lacks the pair: the guard reports it, it does not crash."""
    return Broken(plan.stops, plan.files, "leg_consistency", legs=LegTable(()))


def _breakings(plan: Plan) -> list[Breaking]:
    """The mutations that can be made of this plan, so that a trip without tracks is not thrown away."""
    always: list[Breaking] = [
        _last_stop_dropped,
        _first_stop_dropped,
        _no_stops,
        _anchor_shown_as_a_track,
        _anchor_repeated_between,
        _unknown_item_added,
        _road_leg_differs,
        _first_stop_has_a_road_leg,
        _leg_time_differs,
        _first_stop_has_a_leg_time,
    ]
    with_items: list[Breaking] = [_item_dropped, _item_repeated] if plan.later_positions else []
    tracks: list[Breaking] = (
        [
            _other_direction_version,
            _stop_shows_other_point_count,
            _stop_shows_other_hash,
            _file_vanished,
            _file_differs,
            _track_length_differs,
        ]
        if plan.track_positions()
        else []
    )
    swappable = len({stop.item_id for stop in plan.stops}) > 1
    swaps: list[Breaking] = (
        [_first_stop_swapped_with_the_next, _last_stop_swapped_with_the_previous] if swappable else []
    )
    reversible = any(plan.stops[at].entry != plan.stops[at].exit for at in plan.track_positions())
    excluded = any(not item.included for item in plan.trip.snapshot.items)
    measured = any(stop.leg_km for stop in plan.stops)
    return [
        *always,
        *([_road_leg_nobody_measured] if measured else []),
        *with_items,
        *tracks,
        *swaps,
        *([_entry_and_exit_swapped] if reversible else []),
        *([_excluded_item_added] if excluded else []),
        _place_moved,
    ]


@given(plan=plans())
def test_every_plan_the_assembler_makes_passes(plan: Plan) -> None:
    before = _judged(plan, plan.stops, None)

    violation = plan.guard().check_plan(plan.stops, plan.files)

    assert_state_delta(before, _judged(plan, plan.stops, violation), UNIVERSE, {}, strict=True)
    assert violation is None
    order = (plan.trip.start.id, *(s.item_id for s in plan.stops[1:-1]), plan.trip.end.id)
    assert plan.guard().check_order(order) is None


@given(plan=plans(), data=st.data())
def test_any_single_mutation_of_a_passing_plan_fails_and_names_its_rule(plan: Plan, data: st.DataObject) -> None:
    # Every mutation on every plan: one sampled per plan left some undrawn in all 50 fixed examples of the mutation
    # profile, so the guard's stop-against-snapshot and tampered-leg checks ran in no mutation run.
    for breaking in _breakings(plan):
        note(f"mutation: {breaking.__name__}")
        broken = breaking(plan, data.draw)
        before = _judged(plan, broken.stops, None)

        guard = InvariantGuard(plan.trip.snapshot, broken.legs or plan.trip.legs)
        violation = guard.check_plan(broken.stops, broken.files)

        expected = {"guard.check": set_to(broken.rule)}
        assert_state_delta(before, _judged(plan, broken.stops, violation), UNIVERSE, expected, strict=True)
        assert violation is not None
        assert violation.detail, "a violation says what is wrong"
        if broken.item_id is not None:
            assert broken.item_id in violation.detail, f"the detail names no item: {violation.detail}"


def _order_of(plan: Plan) -> tuple[str, ...]:
    return tuple(stop.item_id for stop in plan.stops)


def _broken_orders(plan: Plan) -> list[tuple[tuple[str, ...], str]]:
    order = _order_of(plan)
    start, end = order[0], order[-1]
    excluded = [item.id for item in plan.trip.snapshot.items if not item.included]
    broken = [
        ((), "HC-2"),
        ((start,), "HC-2"),
        (order[1:], "HC-2"),
        (order[:-1], "HC-2"),
        (("no-such-item", *order), "HC-2"),
        ((*order, "no-such-item"), "HC-2"),
        ((start, "no-such-item", *order[1:]), "HC-3"),
        ((start, start, *order[1:]), "HC-3"),
        ((*order[:-1], end, end), "HC-3"),
    ]
    between = order[1:-1]
    if between:
        broken.append(((start, *between[1:], end), "HC-3"))
        broken.append(((start, between[0], *between, end), "HC-3"))
    broken.extend(((start, item_id, *order[1:]), "HC-3") for item_id in excluded)
    return broken


@given(plan=plans(), data=st.data())
def test_a_chosen_order_breaking_an_anchor_or_an_item_fails_naming_its_rule(plan: Plan, data: st.DataObject) -> None:
    order, rule = data.draw(st.sampled_from(_broken_orders(plan)), label="order")
    before = _judged(plan, plan.stops, None)

    violation = plan.guard().check_order(order)

    assert_state_delta(
        before, _judged(plan, plan.stops, violation), UNIVERSE, {"guard.check": set_to(rule)}, strict=True
    )

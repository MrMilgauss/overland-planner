"""The HC guard on a plan (ADR-009 with Amendments 1 to 3, slice 01b scope plus slice 02's track length and leg time,
slice 03b's retrace form, check 5 after a retrace and reachability claims): every assembled plan passes, every broken
one fails naming its rule.

Driving port: `InvariantGuard` (`check_order`, `check_plan`, `check_unreachable` are its public interface; it is pure).
Observable universe = the guard's result, the stops it judged and the snapshot read.
Test Budget: 6 behaviors (assembled plans pass, a broken plan names its rule, a broken chosen order names its rule,
assembled plans with retraces pass, a broken retrace plan names its rule, an unreachable claim holds only for the items
no order connects) x 2 = 12; 6 used.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

import pytest
from hypothesis import given, note
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import canonical_points_file
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.planning.invariant_guard import (
    CanonicalFileEvidence,
    GuardViolation,
    InvariantGuard,
)
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.planning.plan_run_assembler import PlanRunAssembler
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.domain.planning.trips import (
    POINTS,
    PROJECT,
    Trip,
    reached_at,
    road_time_s,
    track_lengths_m,
    track_points,
    trips,
)

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


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
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


def _ends(first: tuple[str, ...], last: tuple[str, ...], plan: Plan) -> str:
    """HC-2's detail: the first and last stop the order has, and the Start and End it should have."""
    snapshot = plan.trip.snapshot
    return f"the trip runs {first} to {last}, not {snapshot.start_item_id} to {snapshot.end_item_id}"


def _items(extra: list[str], missing: list[str]) -> str:
    """HC-3's detail: the items placed too often or never, by id."""
    return f"not each item once: extra {extra}, missing {missing}"


def _broken_orders(plan: Plan) -> list[tuple[tuple[str, ...], str, str]]:
    """Each broken order with the rule it breaks first and the exact detail the guard gives."""
    order = _order_of(plan)
    start, end = order[0], order[-1]
    excluded = [item.id for item in plan.trip.snapshot.items if not item.included]
    broken = [
        ((), "HC-2", _ends((), (), plan)),
        ((start,), "HC-2", _ends((start,), (start,), plan)),
        (order[1:], "HC-2", _ends((order[1],), (end,), plan)),
        (order[:-1], "HC-2", _ends((start,), (order[-2],), plan)),
        (("no-such-item", *order), "HC-2", _ends(("no-such-item",), (end,), plan)),
        ((*order, "no-such-item"), "HC-2", _ends((start,), ("no-such-item",), plan)),
        ((start, "no-such-item", *order[1:]), "HC-3", _items(["no-such-item"], [])),
        ((start, start, *order[1:]), "HC-3", _items([start], [])),
        ((*order[:-1], end, end), "HC-3", _items([end], [])),
    ]
    between = order[1:-1]
    if between:
        broken.append(((start, *between[1:], end), "HC-3", _items([], [between[0]])))
        broken.append(((start, between[0], *between, end), "HC-3", _items([between[0]], [])))
    broken.extend(((start, item_id, *order[1:]), "HC-3", _items([item_id], [])) for item_id in excluded)
    return broken


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@given(plan=plans())
def test_a_chosen_order_breaking_an_anchor_or_an_item_fails_naming_its_rule(plan: Plan) -> None:
    """Every broken order on every example (D212), each with the exact detail the event log gets."""
    for order, rule, detail in _broken_orders(plan):
        note(f"order: {order}")
        before = _judged(plan, plan.stops, None)

        violation = plan.guard().check_order(order)

        assert_state_delta(
            before, _judged(plan, plan.stops, violation), UNIVERSE, {"guard.check": set_to(rule)}, strict=True
        )
        assert violation is not None and violation.detail == detail


# ------------------------------------------------------------------------------------- slice 03b: retraces (ADR-017)
RETRACE_REASON = "retraces the trail backwards; check it is drivable in reverse"  # the product's words (ADR-017)
DEAD_EXITS = (Coordinate(46.5, 8.5), Coordinate(46.6, 8.6))  # points of their own: no item is reached there
ISOLATED = Coordinate(47.0, 9.0)  # a place no road reaches or leaves
Pair = tuple[Coordinate, Coordinate]


def reversed_sha256(track: TrackItem) -> str:
    """The test's own retrace evidence: the stored points of the track, reversed and serialised afresh."""
    points = track_points(track.entry, track.exit, track.point_count)
    return hashlib.sha256(canonical_points_file(tuple(reversed(points)))).hexdigest()


def _dead_end_track(draw: st.DrawFn, item_id: str, exit_: Coordinate) -> TrackItem:
    entry, point_count = draw(st.sampled_from(POINTS)), draw(st.integers(2, 20))
    canonical = canonical_points_file(track_points(entry, exit_, point_count))
    return TrackItem(
        id=item_id,
        project_id=PROJECT,
        name=f"Dead end {item_id}",
        description=None,
        original_sha256="original",
        canonical_sha256=hashlib.sha256(canonical).hexdigest(),
        direction_version=draw(st.integers(1, 9)),
        point_count=point_count,
        entry=entry,
        exit=exit_,
        length_m=draw(track_lengths_m),
    )


@dataclass(frozen=True)
class DeadEnds:
    """A trip with one or two dead-end tracks (no road at any level leaves their exit) and maybe an isolated place;
    `no_road` holds the pairs the road map has no road for."""

    trip: Trip
    no_road: frozenset[Pair]
    isolated: PoiItem | None = None


@st.composite
def dead_end_trips(draw: st.DrawFn, *, isolated: bool = False) -> DeadEnds:
    trip = draw(trips())
    exits = DEAD_EXITS[: draw(st.integers(1, 2))]
    dead = [_dead_end_track(draw, f"dead-{i}", exit_) for i, exit_ in enumerate(exits)]
    no_road = {(exit_, point) for exit_ in DEAD_EXITS for point in (*POINTS, ISOLATED)}
    alone = PoiItem(id="isolated", project_id=PROJECT, name="Alone", location=ISOLATED) if isolated else None
    if alone is not None:
        no_road |= {pair for point in (*POINTS, *DEAD_EXITS) for pair in ((point, ISOLATED), (ISOLATED, point))}
    added = (*dead, *([alone] if alone else []))
    order = draw(st.permutations((*trip.items, *added)))
    legs = LegTable((RoadLeg(*pair, m, road_time_s(m)) for pair, m in trip.leg_m.items()), no_road)
    snapshot = replace(trip.snapshot, items=(*trip.snapshot.items, *added))
    return DeadEnds(Trip(snapshot, legs, trip.leg_m, trip.start, trip.end, tuple(order)), frozenset(no_road), alone)


def _retrace_evidence_of(track: TrackItem) -> CanonicalFileEvidence:
    return replace(_evidence_of(track), reversed_sha256=reversed_sha256(track))


@st.composite
def retrace_plans(draw: st.DrawFn) -> Plan:
    """A plan the assembler makes of a dead-end trip in any order, with the job's retrace hashes and file evidence."""
    trip = draw(dead_end_trips()).trip
    hashes = {track.id: reversed_sha256(track) for track in trip.tracks()}
    stops = PlanRunAssembler(trip.snapshot, trip.legs).assemble([item.id for item in trip.items], hashes)
    return Plan(trip, stops, {track.id: _retrace_evidence_of(track) for track in trip.tracks()})


def _retraces(plan: Plan) -> list[int]:
    return [at for at, stop in enumerate(plan.stops) if stop.kind == "retrace"]


def _track_of(plan: Plan, at: int) -> TrackItem:
    track = plan.trip.snapshot.item(plan.stops[at].item_id)
    assert isinstance(track, TrackItem)
    return track


def _a_retrace(plan: Plan, draw: st.DrawFn) -> tuple[int, PlanStop, TrackItem]:
    at = draw(st.sampled_from(_retraces(plan)))
    return at, plan.stops[at], _track_of(plan, at)


def _retrace_moved(plan: Plan, draw: st.DrawFn) -> Broken:
    """Check 6, adjacency: anywhere but directly after its own track (never last: that is HC-2's)."""
    at, stop, _ = _a_retrace(plan, draw)
    rest = (*plan.stops[:at], *plan.stops[at + 1 :])
    places = [to for to in range(1, len(rest)) if rest[to - 1].item_id != stop.item_id]
    to = draw(st.sampled_from(places))
    return Broken((*rest[:to], stop, *rest[to:]), plan.files, "retrace", stop.item_id)


def _retrace_repeated(plan: Plan, draw: st.DrawFn) -> Broken:
    at, stop, _ = _a_retrace(plan, draw)
    return Broken(plan.inserted(at + 1, stop), plan.files, "retrace", stop.item_id)


def _retrace_of_another_track(plan: Plan, draw: st.DrawFn) -> Broken:
    at, stop, _ = _a_retrace(plan, draw)
    other = draw(st.sampled_from([track.id for track in plan.trip.tracks() if track.id != stop.item_id]))
    return Broken(plan.with_stop(at, item_id=other), plan.files, "retrace", other)


def _retrace_of_no_track(plan: Plan, draw: st.DrawFn) -> Broken:
    at, _, _ = _a_retrace(plan, draw)
    other = draw(st.sampled_from(("no-such-item", plan.trip.start.id)))
    return Broken(plan.with_stop(at, item_id=other), plan.files, "retrace", other)


def _retrace_runs_entry_to_exit(plan: Plan, draw: st.DrawFn) -> Broken:
    at, stop, track = _a_retrace(plan, draw)
    return Broken(plan.with_stop(at, entry=track.entry, exit=track.exit), plan.files, "retrace", stop.item_id)


def _retrace_ends_at_the_tracks_exit(plan: Plan, draw: st.DrawFn) -> Broken:
    """No stop may end at a track's exit (no mirror case)."""
    at, stop, track = _a_retrace(plan, draw)
    return Broken(plan.with_stop(at, exit=track.exit), plan.files, "retrace", stop.item_id)


def _retrace_says_otherwise(plan: Plan, draw: st.DrawFn) -> Broken:
    at, stop, _ = _a_retrace(plan, draw)
    words = draw(
        st.sampled_from(
            ({"confidence": "confirmed"}, {"confidence": None}, {"reason": "other"}, {"reason": None}, {"kind": "poi"})
        )
    )
    return Broken(plan.with_stop(at, **words), plan.files, "retrace" if "kind" not in words else "HC-3", stop.item_id)


def _retrace_length_differs(plan: Plan, draw: st.DrawFn) -> Broken:
    at, stop, track = _a_retrace(plan, draw)
    length = draw(st.sampled_from((track.length_m / 1000 + 0.001, track.length_m / 2000, None)))
    return Broken(plan.with_stop(at, track_km=length), plan.files, "retrace", stop.item_id)


def _retrace_has_a_road_leg(plan: Plan, draw: st.DrawFn) -> Broken:
    at, stop, _ = _a_retrace(plan, draw)
    changes: tuple[dict[str, Any], ...] = (
        {"leg_km": 0.0},
        {"leg_s": 0},
        {"leg_confidence": "confirmed"},
        {"leg_reason": "a road"},
        {"location": POINTS[0]},
    )
    leg = draw(st.sampled_from(changes))
    return Broken(plan.with_stop(at, **leg), plan.files, "retrace", stop.item_id)


def _retrace_although_a_road_leaves_the_exit(plan: Plan, draw: st.DrawFn) -> Broken:
    at, stop, track = _a_retrace(plan, draw)
    onward = plan.trip.snapshot.item(plan.stops[at + 1].item_id)
    road = LegTable([RoadLeg(track.exit, reached_at(onward), 1, 1)])
    return Broken(plan.stops, plan.files, "retrace", stop.item_id, plan.trip.legs.merged_with(road))


def _retrace_hash_differs(plan: Plan, draw: st.DrawFn) -> Broken:
    at, stop, track = _a_retrace(plan, draw)
    sha = draw(st.sampled_from(("other", None, track.canonical_sha256)))
    return Broken(plan.with_stop(at, retrace_sha256=sha), plan.files, "retrace", stop.item_id)


def _retrace_evidence_differs(plan: Plan, draw: st.DrawFn) -> Broken:
    """The reversed points read from the file are not the ones retraced, or could not be read."""
    _, stop, track = _a_retrace(plan, draw)
    changed = replace(plan.files[track.id], reversed_sha256=draw(st.sampled_from(("other", None))))
    return Broken(plan.stops, {**plan.files, track.id: changed}, "retrace", stop.item_id)


def _retraced_file_vanished(plan: Plan, draw: st.DrawFn) -> Broken:
    _, stop, _ = _a_retrace(plan, draw)
    return Broken(plan.stops, {k: v for k, v in plan.files.items() if k != stop.item_id}, "HC-5", stop.item_id)


def _retrace_dropped(plan: Plan, draw: st.DrawFn) -> Broken:
    """The track is left from its exit, where no road goes: the leg after it is nobody's."""
    at, _, _ = _a_retrace(plan, draw)
    after = plan.stops[at + 1].item_id
    return Broken((*plan.stops[:at], *plan.stops[at + 1 :]), plan.files, "leg_consistency", after)


def _retraced_track_dropped(plan: Plan, draw: st.DrawFn) -> Broken:
    at, stop, _ = _a_retrace(plan, draw)
    return Broken((*plan.stops[: at - 1], *plan.stops[at:]), plan.files, "HC-3", stop.item_id)


def _retraced_track_reversed(plan: Plan, draw: st.DrawFn) -> Broken:
    at, stop, track = _a_retrace(plan, draw)
    return Broken(plan.with_stop(at - 1, entry=track.exit, exit=track.entry), plan.files, "HC-1", stop.item_id)


def _leg_after_the_retrace_from_elsewhere(plan: Plan, draw: st.DrawFn) -> Broken:
    """Check 5 after a retrace: the road goes on from the track's entry, from no other point."""
    at, _, track = _a_retrace(plan, draw)
    onward = plan.stops[at + 1]
    destination = reached_at(plan.trip.snapshot.item(onward.item_id))
    origin = draw(st.sampled_from([point for point in POINTS if point not in (track.entry, destination)]))
    m = plan.trip.leg_m[origin, destination]
    changed = plan.with_stop(at + 1, leg_km=m / 1000, leg_s=road_time_s(m))
    return Broken(changed, plan.files, "leg_consistency", onward.item_id)


RETRACE_BREAKINGS: list[Breaking] = [
    _retrace_moved,
    _retrace_repeated,
    _retrace_of_no_track,
    _retrace_runs_entry_to_exit,
    _retrace_ends_at_the_tracks_exit,
    _retrace_says_otherwise,
    _retrace_length_differs,
    _retrace_has_a_road_leg,
    _retrace_although_a_road_leaves_the_exit,
    _retrace_hash_differs,
    _retrace_evidence_differs,
    _retraced_file_vanished,
    _retrace_dropped,
    _retraced_track_dropped,
    _retraced_track_reversed,
    _leg_after_the_retrace_from_elsewhere,
]


@given(plan=retrace_plans())
def test_every_plan_with_retraces_the_assembler_makes_passes(plan: Plan) -> None:
    before = _judged(plan, plan.stops, None)

    violation = plan.guard().check_plan(plan.stops, plan.files)

    assert_state_delta(before, _judged(plan, plan.stops, violation), UNIVERSE, {}, strict=True)
    assert violation is None, f"{violation}"
    assert _retraces(plan), "a dead-end track is always retraced"
    assert all(
        plan.stops[at].retrace_sha256 == plan.files[plan.stops[at].item_id].reversed_sha256 for at in _retraces(plan)
    )


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@given(plan=retrace_plans(), data=st.data())
def test_any_single_retrace_perturbation_fails_and_names_its_rule(plan: Plan, data: st.DataObject) -> None:
    """Every perturbation of criterion 2 on every plan (D212); none passes."""
    others = [_retrace_of_another_track] if len(plan.trip.tracks()) > 1 else []
    for breaking in [*RETRACE_BREAKINGS, *others]:
        note(f"perturbation: {breaking.__name__}")
        broken = breaking(plan, data.draw)
        before = _judged(plan, broken.stops, None)

        guard = InvariantGuard(plan.trip.snapshot, broken.legs or plan.trip.legs)
        violation = guard.check_plan(broken.stops, broken.files)

        expected = {"guard.check": set_to(broken.rule)}
        assert_state_delta(before, _judged(plan, broken.stops, violation), UNIVERSE, expected, strict=True)
        assert violation is not None and violation.detail
        assert broken.item_id is None or broken.item_id in violation.detail, f"no item named: {violation.detail}"


CLAIM_UNIVERSE = {"guard.check", "snapshot.read"}


@given(dead_ends=dead_end_trips(isolated=True), data=st.data())
def test_an_unreachable_claim_holds_only_for_the_items_no_order_connects(
    dead_ends: DeadEnds, data: st.DataObject
) -> None:
    """ADR-009 Amendment 1: the claim is re-derived from the leg table. Here only the isolated place is cut off: every
    other item has a road from every point, and a dead end its retrace."""
    trip, alone = dead_ends.trip, dead_ends.isolated
    assert alone is not None
    connected: list[CatalogItem] = [item for item in trip.items if item.id != alone.id]
    guard = InvariantGuard(trip.snapshot, trip.legs)
    wrong = data.draw(st.sampled_from([*(item.id for item in connected), "no-such-item"]), label="wrongly claimed")
    claims = [((alone.id,), None), ((alone.id, wrong), "reachability"), ((wrong,), "reachability")]
    for claim, rule in claims:
        note(f"claim: {claim}")
        before = {"guard.check": None, "snapshot.read": trip.snapshot}

        violation = guard.check_unreachable(claim)

        after = {"guard.check": None if violation is None else violation.check, "snapshot.read": trip.snapshot}
        assert_state_delta(before, after, CLAIM_UNIVERSE, {"guard.check": set_to(rule)} if rule else {}, strict=True)
        assert violation is None or wrong in violation.detail, f"the detail names no item: {violation}"

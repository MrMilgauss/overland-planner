"""HC-1 over levels (US-19, A-7, K2/K3, ADR-017): every plan assembled for a trip whose road legs have levels
(Confirmed, Unconfirmed, none) and whose dead-end tracks lead nowhere has no track driven exit -> entry, each retrace
directly after its own track and nowhere else, the road onward from the track's entry, and totals that keep retraces
off the road. Any order is assembled, not only the solver's.

Driving ports: `PlanRunAssembler.assemble`, `Totals.of` and `InvariantGuard.check_plan`, all pure.
Observable universe = the stops as the itinerary reads them (track rows, retrace rows and what follows them, totals)
and the guard's verdict. The oracle states the ADR-017 rule on the road map's answers (a retrace exactly where no
road leaves the track's exit toward the next stop; the road then goes on from the track's entry); it does not call
`retrace_rule`, the one definition.
Test Budget: 2 behaviors (the retrace form of every assembled plan, the scenario's two oracles catch a bad plan)
x 2 = 4; 2 used (the second parametrized over the five mutated plans of DISTILL).

Marker decision (07-10, criterion 4): `HYPOTHESIS_PROFILE=ci` (1,000 cases), this property alone, 2026-11-11: 1.9 s
(< 3 s), so the property stays unmarked and 07-13 omits the marker change for this file (D221).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from itertools import pairwise
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import (
    canonical_file_sha256,
    parse_canonical_points_file,
    reversed_points_sha256,
)
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.planning.invariant_guard import CanonicalFileEvidence, InvariantGuard
from overland_planner.domain.planning.plan_run import PlanStop, Totals
from overland_planner.domain.planning.plan_run_assembler import PlanRunAssembler
from tests.acceptance.overland_route_planner_mvp.steps.retrace_steps import (
    SparseProject,
    retraced_tracks,
    reversed_track_stops,
    sommeiller_on_the_way_to_briancon,
)
from tests.common.state_delta import assert_state_delta, set_to, unchanged
from tests.unit.domain.planning.test_plan_run_assembler import RETRACE_REASON, Pair, close_to, dead_end_trips
from tests.unit.domain.planning.trips import Trip, canonical_file_of, left_at, reached_at


def _evidence(trip: Trip) -> tuple[dict[str, CanonicalFileEvidence], dict[str, str]]:
    """What the job reads of the stored files: the guard's evidence and the hash of each track's reversed points."""
    files, reversed_hashes = {}, {}
    for track in trip.tracks():
        content = canonical_file_of(track)
        points = parse_canonical_points_file(content)
        reversed_hash = reversed_points_sha256(points)
        files[track.id] = CanonicalFileEvidence(
            canonical_file_sha256(content), len(points), points[0].coordinate, points[-1].coordinate, reversed_hash
        )
        reversed_hashes[track.id] = reversed_hash
    return files, reversed_hashes


def _levelled_rows(
    trip: Trip, order: tuple[CatalogItem, ...], no_road: set[Pair], unconfirmed: set[Pair]
) -> list[tuple[Any, ...]]:
    """The expected rows as (kind, item id, road leg km, s, level) worked out from the rule: a track whose exit has no
    road to the next stop is followed by its retrace row (no leg), and the road goes on from the track's entry."""
    sequence = (trip.start, *order, trip.end)
    rows: list[tuple[Any, ...]] = [("poi", trip.start.id, None, None, None)]
    for previous, item in pairwise(sequence):
        origin = left_at(previous)
        if (origin, reached_at(item)) in no_road:
            assert isinstance(previous, TrackItem)
            rows.append(("retrace", previous.id, None, None, None))
            origin = previous.entry
        pair = (origin, reached_at(item))
        level = "unconfirmed" if pair in unconfirmed else "confirmed"
        kind = "track" if isinstance(item, TrackItem) else "poi"
        rows.append((kind, item.id, trip.road_m(*pair) / 1000, trip.road_s(*pair), level))
    return rows


@given(dead_ends=dead_end_trips(), data=st.data())
def test_every_assembled_plan_has_its_retraces_right_after_their_tracks_and_is_accepted_by_the_guard(
    dead_ends: tuple[Trip, Any, set[Pair], set[Pair]], data: st.DataObject
) -> None:
    trip, legs, no_road, unconfirmed = dead_ends
    order = tuple(data.draw(st.permutations(trip.items), label="order"))
    files, reversed_hashes = _evidence(trip)
    stops = PlanRunAssembler(trip.snapshot, legs).assemble([item.id for item in order], reversed_hashes)
    retraced_at = [number for number, stop in enumerate(stops) if stop.kind == "retrace"]
    universe = {
        "snapshot.read",
        "plan.track_rows",
        "plan.retraces",
        "plan.legs_after_retraces",
        "plan.totals",
        "plan.guard",
    }
    before = {slot: None for slot in universe} | {"snapshot.read": trip.snapshot}

    after = {
        "snapshot.read": trip.snapshot,
        "plan.track_rows": tuple((s.item_id, s.entry, s.exit) for s in stops if s.kind == "track"),
        "plan.retraces": tuple(
            (
                n,
                stops[n].item_id,
                stops[n].entry,
                stops[n].exit,
                stops[n - 1].kind,
                stops[n - 1].item_id,
                stops[n].reason,
            )
            for n in retraced_at
        ),
        "plan.legs_after_retraces": tuple(
            (stops[n + 1].leg_km, stops[n + 1].leg_s, stops[n + 1].leg_confidence) for n in retraced_at
        ),
        "plan.totals": _totals_row(Totals.of(stops)),
        "plan.guard": InvariantGuard(trip.snapshot, legs).check_plan(stops, files),
    }

    expected = _levelled_rows(trip, order, no_road, unconfirmed)
    tracks = {item.id: item for item in trip.tracks()}
    wanted_retraces = tuple(
        (n, item_id, tracks[item_id].exit, tracks[item_id].entry, "track", item_id, RETRACE_REASON)
        for n, (kind, item_id, *_) in enumerate(expected)
        if kind == "retrace"
    )
    legs_after = tuple(expected[n + 1][2:5] for n, *_ in wanted_retraces)
    retraced_tracks_km = [tracks[item_id].length_m / 1000 for _, item_id, *_ in wanted_retraces]
    driven_km = [i.length_m / 1000 for i in order if isinstance(i, TrackItem)]
    road_km = [row[2] for row in expected if row[2] is not None]
    road_s = [row[3] for row in expected if row[3] is not None]
    offroad_km = math.fsum([*driven_km, *retraced_tracks_km])
    offroad_s = math.fsum(km / trip.speed.kmh * 3600 for km in [*driven_km, *retraced_tracks_km])
    totals = (
        math.fsum(road_km),
        sum(road_s),
        offroad_km,
        offroad_s,
        math.fsum(road_km) + offroad_km,
        sum(road_s) + offroad_s,
    )
    assert_state_delta(
        before,
        after,
        universe,
        {
            "snapshot.read": unchanged(),
            "plan.track_rows": set_to(tuple((i.id, i.entry, i.exit) for i in order if isinstance(i, TrackItem))),
            "plan.retraces": set_to(wanted_retraces),
            "plan.legs_after_retraces": close_to(legs_after),
            "plan.totals": close_to(totals),
            "plan.guard": set_to(None),
        },
        strict=True,
    )
    assert len({item_id for _, item_id, *_ in wanted_retraces}) == len(wanted_retraces), "a track is retraced twice"


def _totals_row(totals: Totals) -> tuple[Any, ...]:
    return (totals.road_km, totals.road_s, totals.offroad_km, totals.offroad_s, totals.total_km, totals.total_s)


# ------------------------------------------------------------------------------ the scenario's two oracles
def _plan_with_a_retrace(project: SparseProject) -> list[PlanStop]:
    """Casa Marco, the Assietta, the Sommeiller (a dead end) and its retrace, Passo Giau, Briancon."""
    snapshot = project.snapshot
    driven = [snapshot.item(item_id) for item_id in ("start", "assietta", "sommeiller")]
    onward = [snapshot.item(item_id) for item_id in ("passo", "end")]
    return [
        PlanStop.driving(driven[0], None),
        *(PlanStop.driving(item, (10.0, 600)) for item in driven[1:]),
        PlanStop.retracing(snapshot.item("sommeiller")),  # type: ignore[arg-type]
        *(PlanStop.driving(item, (10.0, 600)) for item in onward),
    ]


def _swap_retrace_with_its_track(stops: list[PlanStop]) -> list[PlanStop]:
    return [*stops[:2], stops[3], stops[2], *stops[4:]]


def _retrace_of_another_item(stops: list[PlanStop]) -> list[PlanStop]:
    return [*stops[:3], replace(stops[3], item_id="assietta"), *stops[4:]]


def _flip(stop: PlanStop) -> PlanStop:
    return replace(stop, entry=stop.exit, exit=stop.entry)


MUTATED_PLANS: list[tuple[str, Callable[[list[PlanStop]], list[PlanStop]], str]] = [
    ("reversed track", lambda s: [*s[:2], _flip(s[2]), *s[3:]], "reversed_track_stops"),
    ("retrace before its track", _swap_retrace_with_its_track, "retraced_tracks"),
    ("retrace of another item", _retrace_of_another_item, "retraced_tracks"),
    ("retrace entry -> exit", lambda s: [*s[:3], _flip(s[3]), *s[4:]], "retraced_tracks"),
    ("missing retrace", lambda s: [*s[:3], *s[4:]], "retraced_tracks"),
]


def _oracle_objects(project: SparseProject, stops: tuple[PlanStop, ...], oracle: str) -> bool:
    """Whether the named oracle of the scenario rejects these stops (True) or lets them through (False)."""
    if oracle == "reversed_track_stops":
        return reversed_track_stops(project, stops) != []
    try:
        retraced = retraced_tracks(project, stops)
    except AssertionError:
        return True
    driven_dead_ends = sorted(t.id for t in project.tracks_to_drive() if t.id in project.dead_ends)
    return sorted(retraced) != driven_dead_ends


def test_the_scenarios_oracles_accept_the_right_plan_and_reject_each_mutated_one() -> None:
    # bypass: a single worked example per mutation; the oracles are the instrument under test, not a quantified rule.
    project = sommeiller_on_the_way_to_briancon()
    right = _plan_with_a_retrace(project)
    verdicts = {
        "right plan": [_oracle_objects(project, tuple(right), o) for o in ("reversed_track_stops", "retraced_tracks")]
    }
    for name, mutate, _ in MUTATED_PLANS:
        verdicts[name] = [
            _oracle_objects(project, tuple(mutate(right)), o) for o in ("reversed_track_stops", "retraced_tracks")
        ]

    caught_by = {
        name: [o for o, hit in zip(("reversed_track_stops", "retraced_tracks"), hits, strict=True) if hit]
        for name, hits in verdicts.items()
    }
    assert caught_by == {
        "right plan": [],
        **{name: [oracle] for name, _, oracle in MUTATED_PLANS},
    }

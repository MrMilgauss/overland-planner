"""Generated dead-end trips for the retrace tests (ADR-017): the trips, their oracle words and the float-tolerant
predicate, shared by the assembler, retrace-plan, guard and plan-job tests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from hypothesis import strategies as st

from overland_planner.application.catalog.facade import canonical_points_file
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg
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


@st.composite
def levelled_dead_end_trips(draw: st.DrawFn) -> tuple[Trip, LegTable, set[Pair], set[Pair]]:
    """A trip whose road legs have levels and where some tracks' exits lead nowhere: no road at any level from such an
    exit to any other point. Only a point no item is reached at can be a dead exit, so every entry keeps its roads.
    Returns the trip, its leg table, the pairs with no road and the pairs whose road is Unconfirmed."""
    trip = draw(trips())
    reached = {reached_at(item) for item in (trip.start, trip.end, *trip.items)}
    exits = sorted({track.exit for track in trip.tracks() if track.exit not in reached}, key=str)
    dead = set(draw(st.lists(st.sampled_from(exits), unique=True))) if exits else set()
    no_road = {pair for pair in trip.leg_m if pair[0] in dead}
    roads = sorted(set(trip.leg_m) - no_road, key=str)
    unconfirmed = set(draw(st.lists(st.sampled_from(roads), unique=True))) if roads else set()
    legs = [
        RoadLeg(*pair, m, road_time_s(m), *level_of(pair, unconfirmed))
        for pair, m in trip.leg_m.items()
        if pair not in no_road
    ]
    return trip, LegTable(legs, no_road), no_road, unconfirmed


def level_of(pair: Pair, unconfirmed: set[Pair]) -> tuple[str, str | None]:
    return ("unconfirmed", f"reason {pair}") if pair in unconfirmed else ("confirmed", None)

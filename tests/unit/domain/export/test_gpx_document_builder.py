"""The stored itinerary becomes the GPX document's waypoints and tracks (US-02b, D10, ADR-010).

Driving port: `GpxDocumentBuilder.build`, pure. Observable universe: the document's `name`, `description`, `waypoints`
and `tracks`, each as it would be written.
Test Budget: 4 behaviors (waypoints are the distinct POI items with only a round-trip anchor suffixed; road legs are
straight named tracks, one fewer than the stops; trails keep their points, in itinerary order among the legs; the
document is labelled by its run; a retrace is its own leg of the track reversed and a leg is marked when it is
Unconfirmed) x 2 = 12; 7 used.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.export.gpx_document import GpxDocument
from overland_planner.domain.export.gpx_document_builder import GpxDocumentBuilder
from overland_planner.domain.planning.plan_run import PlanStop
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"name", "description", "waypoints", "tracks"}
ROAD_LEGS_UNIVERSE = {"road_legs"}

CASA = Coordinate(45.07, 7.68)
BRIANCON = Coordinate(44.9, 6.64)
ENTRY = TrackPoint.at(45.05, 7.04, 1650.0)
MIDDLE = TrackPoint.at(45.0, 6.95)
EXIT = TrackPoint.at(44.96, 6.88, 1530.0)


def _view(document: GpxDocument) -> dict[str, Any]:
    return {
        "name": document.name,
        "description": document.description,
        "waypoints": tuple((point.name, point.location, point.description) for point in document.waypoints),
        "tracks": tuple(
            (track.name, track.number, track.kind, track.description, track.points) for track in document.tracks
        ),
    }


def _poi(item_id: str, name: str, place: Coordinate, leg_km: float | None = 1.0) -> PlanStop:
    return PlanStop(item_id=item_id, name=name, kind="poi", leg_km=leg_km, location=place)


def _trail(item_id: str, name: str, points: tuple[TrackPoint, ...]) -> PlanStop:
    return PlanStop(
        item_id=item_id,
        name=name,
        kind="track",
        leg_km=1.0,
        entry=points[0].coordinate,
        exit=points[-1].coordinate,
        direction_version=1,
        point_count=len(points),
        canonical_sha256="hash",
    )


@dataclass(frozen=True)
class _Plan:
    number: int
    stops: tuple[PlanStop, ...]
    trail_points: dict[str, tuple[TrackPoint, ...]]
    waypoints: tuple[tuple[str, Coordinate, None], ...]

    def built(self) -> GpxDocument:
        return GpxDocumentBuilder(self.number, self.stops, self.trail_points).build()

    def tracks(self) -> tuple[tuple[str, int, str, None, tuple[TrackPoint, ...]], ...]:
        """Every stop but the first is reached by its road leg; a trail follows the leg that reaches it."""
        rows: list[tuple[str, int, str, None, tuple[TrackPoint, ...]]] = []
        for number, stop in enumerate(self.stops, start=1):
            if number > 1:
                previous = self.stops[number - 2]
                ends = (TrackPoint(previous.exit or _at(previous)), TrackPoint(stop.entry or _at(stop)))
                rows.append((f"Leg {number - 1}: {previous.name} -> {stop.name}", number - 1, "road", None, ends))
            if stop.kind == "track":
                rows.append((stop.name, number, "offroad", None, self.trail_points[stop.item_id]))
        return tuple(rows)


def _at(stop: PlanStop) -> Coordinate:
    assert stop.location is not None
    return stop.location


_places = st.builds(Coordinate, st.floats(-90, 90), st.floats(-180, 180))
_names = st.text(alphabet="Ab ,'->", min_size=1, max_size=5)  # few letters, so different items often share a name
_points = st.builds(TrackPoint, _places, st.none() | st.floats(-500, 9000))
_trail_rows = st.tuples(st.just("track"), _names, st.lists(_points, min_size=2, max_size=6).map(tuple))
_poi_rows = st.tuples(st.just("poi"), _names, _places)


def _plan_of(
    number: int, start: tuple[str, Coordinate], end: tuple[str, Coordinate] | None, middle: list[tuple[str, str, Any]]
) -> _Plan:
    stops = [_poi("start", start[0], start[1], None)]
    points: dict[str, tuple[TrackPoint, ...]] = {}
    waypoints = []
    for position, (kind, name, content) in enumerate(middle):
        item_id = f"item-{position}"
        if kind == "track":
            stops.append(_trail(item_id, name, content))
            points[item_id] = content
        else:
            stops.append(_poi(item_id, name, content))
            waypoints.append((name, content, None))
    if end is None:
        stops.append(_poi("start", start[0], start[1]))
        return _Plan(number, tuple(stops), points, ((f"{start[0]} (S/E)", start[1], None), *waypoints))
    stops.append(_poi("end", end[0], end[1]))
    return _Plan(number, tuple(stops), points, ((start[0], start[1], None), *waypoints, (end[0], end[1], None)))


_plans = st.builds(
    _plan_of,
    st.integers(1, 10_000),
    st.tuples(_names, _places),
    st.none() | st.tuples(_names, _places),
    st.lists(_trail_rows | _poi_rows, max_size=5),
)


@given(plan=_plans)
def test_any_plan_becomes_its_waypoints_and_its_legs_and_trails_in_itinerary_order(plan: _Plan) -> None:
    assert_state_delta(
        _view(GpxDocument()),
        _view(plan.built()),
        UNIVERSE,
        {
            "name": set_to(f"Plan run #{plan.number}"),
            "description": set_to(None),
            "waypoints": set_to(plan.waypoints),
            "tracks": set_to(plan.tracks()),
        },
        strict=True,
    )


@given(plan=_plans)
def test_road_legs_are_one_fewer_than_the_stops_and_each_a_straight_line(plan: _Plan) -> None:
    def _straight_legs(_old: Any, new: tuple[tuple[TrackPoint, ...], ...]) -> bool:
        return len(new) == len(plan.stops) - 1 and all(len(points) == 2 for points in new)

    road_legs = tuple(track.points for track in plan.built().tracks if track.kind == "road")

    assert_state_delta(
        {"road_legs": ()}, {"road_legs": road_legs}, ROAD_LEGS_UNIVERSE, {"road_legs": _straight_legs}, strict=True
    )


def test_a_round_trip_reads_as_the_plan_marco_sees() -> None:
    # bypass: the literal file of the slice's story, written by hand; the properties above state the rule.
    points = (ENTRY, MIDDLE, EXIT)
    stops = (
        _poi("casa", "Casa Marco, Torino", CASA, None),
        _trail("assietta", "Strada dell'Assietta", points),
        _poi("briancon", "Briancon", BRIANCON),
        _poi("casa", "Casa Marco, Torino", CASA),
    )

    document = GpxDocumentBuilder(1, stops, {"assietta": points}).build()

    assert_state_delta(
        _view(GpxDocument()),
        _view(document),
        UNIVERSE,
        {
            "name": set_to("Plan run #1"),
            "waypoints": set_to(
                (("Casa Marco, Torino (S/E)", CASA, None), ("Briancon", BRIANCON, None)),
            ),
            "tracks": set_to(
                (
                    (
                        "Leg 1: Casa Marco, Torino -> Strada dell'Assietta",
                        1,
                        "road",
                        None,
                        (TrackPoint(CASA), TrackPoint(ENTRY.coordinate)),
                    ),
                    ("Strada dell'Assietta", 2, "offroad", None, points),
                    (
                        "Leg 2: Strada dell'Assietta -> Briancon",
                        2,
                        "road",
                        None,
                        (TrackPoint(EXIT.coordinate), TrackPoint(BRIANCON)),
                    ),
                    (
                        "Leg 3: Briancon -> Casa Marco, Torino",
                        3,
                        "road",
                        None,
                        (TrackPoint(BRIANCON), TrackPoint(CASA)),
                    ),
                ),
            ),
        },
        strict=True,
    )


def test_a_zero_length_leg_still_appears_as_a_two_point_track() -> None:
    # bypass: one fixed geometry: a trail that starts exactly where the Start place is.
    points = (TrackPoint(CASA), EXIT)
    stops = (
        _poi("casa", "Casa", CASA, None),
        _trail("trail", "Trail", points),
        _poi("casa", "Casa", CASA),
    )

    legs = [track for track in GpxDocumentBuilder(1, stops, {"trail": points}).build().tracks if track.kind == "road"]

    assert_state_delta(
        {"road_legs": ()},
        {"road_legs": tuple((track.name, track.points) for track in legs)},
        ROAD_LEGS_UNIVERSE,
        {
            "road_legs": set_to(
                (
                    ("Leg 1: Casa -> Trail", (TrackPoint(CASA), TrackPoint(CASA))),
                    ("Leg 2: Trail -> Casa", (TrackPoint(EXIT.coordinate), TrackPoint(CASA))),
                )
            )
        },
        strict=True,
    )


# bypass: the two itineraries too short to be a round trip; they have no content to vary.
@pytest.mark.parametrize(
    ("stops", "waypoints"),
    [((), ()), ((_poi("casa", "Casa", CASA, None),), (("Casa", CASA, None),))],
)
def test_an_itinerary_too_short_to_return_names_no_anchor_and_no_leg(
    stops: tuple[PlanStop, ...], waypoints: tuple[tuple[str, Coordinate, None], ...]
) -> None:
    assert_state_delta(
        _view(GpxDocument()),
        _view(GpxDocumentBuilder(7, stops, {}).build()),
        UNIVERSE,
        {"name": set_to("Plan run #7"), "waypoints": set_to(waypoints)},
        strict=True,
    )


_RETRACE_REASON = "retraces the trail backwards; check it is drivable in reverse"
_reasons = st.none() | st.text(alphabet="abc 12.-,", min_size=1, max_size=12)
_levels = st.tuples(st.sampled_from(["confirmed", "unconfirmed"]), _reasons)
_long_points = st.lists(_points, min_size=3, max_size=5).map(tuple).filter(lambda points: points != points[::-1])
_kinds = st.sampled_from(["poi", "track", "retrace"])


@dataclass(frozen=True)
class _Marked:
    """Any itinerary, retraces anywhere (first, last, consecutive) and any legs Unconfirmed; the oracle is the file the
    story states, written leg by leg without the builder."""

    stops: tuple[PlanStop, ...]
    pool: dict[str, tuple[TrackPoint, ...]]
    expected: tuple[tuple[str, int, str, tuple[TrackPoint, ...]], ...]

    def built(self) -> GpxDocument:
        return GpxDocumentBuilder(1, self.stops, self.pool).build()


def _marked_plan(
    pool_points: list[tuple[TrackPoint, ...]],
    rows: list[tuple[str, int, tuple[Literal["confirmed", "unconfirmed"], str | None]]],
) -> _Marked:
    pool = {f"track-{index}": points for index, points in enumerate(pool_points)}
    stops: list[PlanStop] = []
    for position, (kind, pick, (level, reason)) in enumerate(rows):
        track_id = f"track-{pick % len(pool_points)}"
        points = pool[track_id]
        if kind == "retrace":
            stops.append(
                PlanStop(
                    track_id, f"Retrace {track_id}", "retrace", None,
                    entry=points[-1].coordinate, exit=points[0].coordinate,
                    confidence="unconfirmed", reason=_RETRACE_REASON,
                )
            )  # fmt: skip
            continue
        stop = (
            _poi(f"poi-{position}", f"P{position}", Coordinate(position + 1.0, 2.0))
            if kind == "poi"
            else _trail(track_id, track_id, points)
        )
        stops.append(replace(stop, leg_km=None if position == 0 else 1.0, leg_confidence=level, leg_reason=reason))
    return _Marked(tuple(stops), pool, _file_of(stops, pool))


def _suffix(reason: str | None) -> str:
    return f" [UNCONFIRMED - {reason}]" if reason else " [UNCONFIRMED]"


def _file_of(
    stops: list[PlanStop], pool: dict[str, tuple[TrackPoint, ...]]
) -> tuple[tuple[str, int, str, tuple[TrackPoint, ...]], ...]:
    rows: list[tuple[str, int, str, tuple[TrackPoint, ...]]] = []
    legs = 0
    for number, stop in enumerate(stops, start=1):
        if stop.kind == "retrace":
            name = f"{stop.name}{_suffix(stop.reason)}"
            rows.append((name, number, "retrace", pool[stop.item_id][::-1]))
            continue
        if number > 1:
            legs += 1
            origin = stops[number - 2]
            left = origin.exit if origin.kind != "poi" else origin.location
            reached = stop.entry if stop.kind == "track" else stop.location
            assert left is not None
            assert reached is not None
            marked = _suffix(stop.leg_reason) if stop.leg_confidence == "unconfirmed" else ""
            ends = (TrackPoint(left), TrackPoint(reached))
            rows.append((f"Leg {legs}: {origin.name} -> {stop.name}{marked}", number - 1, "road", ends))
        if stop.kind == "track":
            rows.append((stop.name, number, "offroad", pool[stop.item_id]))
    return tuple(rows)


_marked_plans = st.builds(
    _marked_plan,
    st.lists(_long_points, min_size=1, max_size=3),
    st.lists(st.tuples(_kinds, st.integers(0, 9), _levels), min_size=1, max_size=7),
)


@given(plan=_marked_plans)
def test_a_retrace_is_its_own_marked_leg_and_every_unconfirmed_leg_is_marked(plan: _Marked) -> None:
    document = plan.built()

    assert_state_delta(
        {"tracks": ()},
        {"tracks": tuple((t.name, t.number, t.kind, t.points) for t in document.tracks)},
        {"tracks"},
        {"tracks": set_to(plan.expected)},
        strict=True,
    )


@given(plan=_marked_plans)
def test_a_trail_is_written_once_forwards_and_its_reverse_only_as_a_retrace(plan: _Marked) -> None:
    stored = [stop.item_id for stop in plan.stops if stop.kind == "track"]
    backwards = {points[::-1] for points in plan.pool.values()}

    document = plan.built()

    written = tuple((track.name, track.points) for track in document.tracks if track.kind == "offroad")
    reversed_as = {track.kind for track in document.tracks if track.points in backwards}
    assert_state_delta(
        {"offroad": (), "reverse_kinds": set()},
        {"offroad": written, "reverse_kinds": reversed_as},
        {"offroad", "reverse_kinds"},
        {
            "offroad": set_to(
                tuple((stop.name, plan.pool[stop.item_id]) for stop in plan.stops if stop.kind == "track")
            ),
            "reverse_kinds": set_to({"retrace"} if any(s.kind == "retrace" for s in plan.stops) else set()),
        },
        strict=True,
    )
    assert len(written) == len(stored)

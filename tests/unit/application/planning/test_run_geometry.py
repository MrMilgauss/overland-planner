"""The run's lines and markers for the map (slice 09, ADR-007 Amendment 2, D251-D254).

Driving port: `RunGeometryService.geometry` from the planning facade. Driven ports: the plan run repository (in-memory
unit of work), the file store (canonical points by direction version), the road map's shapes (a double of the routing
port's `route_shape`) and the event log. Observable universe: the answer's lines and markers, the road-map calls made
and the `plan.run.geometry_served` line.
Test Budget: 6 behaviors (lines in itinerary order with the direction they are driven; thinning of a long track;
shapes when the road map's identity changed; shapes when the engine fails part-way; markers; refusals and the served
line) x 2 = 12; 6 used.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import canonical_points_file
from overland_planner.application.planning.facade import (
    PlanRunNotFoundError,
    PlanRunQueries,
    RunGeometry,
    RunGeometryService,
    RunHasNoRouteError,
)
from overland_planner.application.ports.file_store import CanonicalPointsMissing
from overland_planner.application.ports.plan_run_repository import NewPlanRun
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.routing_provider import ProviderUnreachable
from overland_planner.application.routing.facade import RoadMapKey, ShapeStore
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.planning.plan_run import RETRACE_REASON, PlanStop
from overland_planner.domain.routing.road_leg import RoadLevel
from overland_planner.domain.routing.road_shape import RoadShape
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.unit.application.planning.planning_doubles import InMemoryPlanning

ROAD_MAP: RoadMapKey = ("engine-2026-11", "4x4.v1")
RUN_ID = "run-1"
UNCONFIRMED_REASON = "exit is 1.2 km from the nearest road - check on the ground"


def at(index: int) -> Coordinate:
    """A place of its own, 0.01 degrees from the previous index."""
    return Coordinate(40.0 + index * 0.001, 7.0 + index * 0.001)


class Engine:
    """The road map's `route_shape`: a bent line through a midpoint. With `fail_from` it fails for the legs from the
    `fail_from`-th of `legs` (the run's road legs in itinerary order) on, whichever call reaches it first, so the
    outcome does not depend on thread timing; `answered` are the legs it answered, `most_at_once` the most calls it
    ever had in flight."""

    provider_id = ROAD_MAP[0]
    profile = ROAD_MAP[1]

    def __init__(self, *, fail_from: int | None = None, legs: Sequence[tuple[Coordinate, Coordinate]] = ()) -> None:
        self._fail_from = fail_from
        self._legs = list(legs)
        self.answered: list[tuple[Coordinate, Coordinate]] = []
        self._lock = threading.Lock()
        self.asked: list[tuple[Coordinate, Coordinate]] = []
        self.most_at_once = 0
        self._in_flight = 0

    def route_shape(self, origin: Coordinate, destination: Coordinate) -> RoadShape:
        with self._lock:
            self.asked.append((origin, destination))
            self._in_flight += 1
            self.most_at_once = max(self.most_at_once, self._in_flight)
        try:
            if self._fail_from is not None and self._legs.index((origin, destination)) + 1 >= self._fail_from:
                raise ProviderUnreachable("the engine is down")
            with self._lock:
                self.answered.append((origin, destination))
            return RoadShape((origin, bent(origin, destination), destination), available=True)
        finally:
            with self._lock:
                self._in_flight -= 1

    def matrix(self, *_: object, **__: object) -> Sequence[Sequence[None]]:
        raise AssertionError("the map asks for shapes, never for legs")

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


def bent(origin: Coordinate, destination: Coordinate) -> Coordinate:
    return Coordinate(
        (origin.latitude + destination.latitude) / 2 + 0.0001, (origin.longitude + destination.longitude) / 2
    )


@dataclass(frozen=True)
class Row:
    """One itinerary row of a generated run: a place, a trail of `points` points, or the retrace of the trail before."""

    kind: str  # poi | track | retrace
    points: int = 0
    level: RoadLevel = "confirmed"


@st.composite
def itineraries(draw: st.DrawFn) -> tuple[bool, tuple[Row, ...]]:
    """Whether Start and End are one place, and the rows between them (a retrace only right after its trail)."""
    middle: list[Row] = []
    for _ in range(draw(st.integers(0, 5))):
        level = draw(st.sampled_from(("confirmed", "unconfirmed")))
        if draw(st.booleans()):
            middle.append(Row("poi", level=level))
            continue
        middle.append(Row("track", draw(st.integers(2, 12)), level))
        if draw(st.booleans()):
            middle.append(Row("retrace"))
    return draw(st.booleans()), tuple(middle)


class Trip:
    """A stored run built from rows, with its canonical files, and how the map should read it."""

    def __init__(
        self,
        round_trip: bool,
        middle: Sequence[Row],
        *,
        provider_id: str = ROAD_MAP[0],
        direction_version: int | None = 2,
    ) -> None:
        self.direction_version = direction_version
        self.files = InMemoryFileStore()
        self.events = RecordingEventLog()
        self.planning = InMemoryPlanning()
        self.stops: list[PlanStop] = []
        self.next_place = 0
        self.tracks: dict[str, tuple[Coordinate, ...]] = {}
        rows = (Row("poi"), *middle, Row("poi"))
        for number, row in enumerate(rows, start=1):
            self.stops.append(self._stop(number, row, round_trip and number == len(rows)))
        self._store(provider_id)

    def _place(self) -> Coordinate:
        self.next_place += 1
        return at(self.next_place)

    def _stop(self, number: int, row: Row, ends_where_it_began: bool) -> PlanStop:
        reason = UNCONFIRMED_REASON if row.level == "unconfirmed" else None
        leg = None if number == 1 else 1.0
        if row.kind == "retrace":
            track = self.stops[-1]
            assert track.entry is not None and track.exit is not None
            return PlanStop(
                track.item_id,
                f"Retrace {track.name}",
                "retrace",
                None,
                entry=track.exit,
                exit=track.entry,
                confidence="unconfirmed",
                reason=RETRACE_REASON,
            )
        if row.kind == "track":
            points = tuple(self._place() for _ in range(row.points))
            item_id = f"track-{number}"
            self.tracks[item_id] = points
            self.files.keep_canonical_points(item_id, 2, canonical_points_file([TrackPoint(point) for point in points]))
            return PlanStop(
                item_id,
                f"Trail {number}",
                "track",
                leg,
                entry=points[0],
                exit=points[-1],
                direction_version=self.direction_version,
                leg_confidence=row.level,
                leg_reason=reason,
            )
        first = self.stops[0] if ends_where_it_began else None
        if first is not None:
            return PlanStop(
                first.item_id,
                first.name,
                "poi",
                leg,
                location=first.location,
                leg_confidence=row.level,
                leg_reason=reason,
            )
        return PlanStop(
            f"poi-{number}",
            f"Place {number}",
            "poi",
            leg,
            location=self._place(),
            leg_confidence=None if number == 1 else row.level,
            leg_reason=reason,
        )

    def _store(self, provider_id: str) -> None:
        self.planning.runs.append(
            NewPlanRun(
                id=RUN_ID,
                project_id="project-1",
                number=4,
                status="ready",
                failure_reason=None,
                created_at=datetime(2026, 11, 17, tzinfo=UTC),
                revision=1,
                provider_id=provider_id,
                objective="distance",
                inputs={},
                stops=tuple(self.stops),
                profile=ROAD_MAP[1],
            )
        )

    def service(self, engine: Engine, identity: RoadMapKey = ROAD_MAP) -> RunGeometryService:
        return RunGeometryService(
            PlanRunQueries(self.planning.unit_of_work),
            self.files,
            ShapeStore(engine),
            lambda: identity,
            self.events,
            FakeClock(),
        )

    def departure(self, stop: PlanStop) -> Coordinate:
        place = stop.exit if stop.kind != "poi" else stop.location
        assert place is not None
        return place

    def arrival(self, stop: PlanStop) -> Coordinate:
        place = stop.entry if stop.kind != "poi" else stop.location
        assert place is not None
        return place

    def road_legs(self) -> list[tuple[Coordinate, Coordinate]]:
        """(origin, destination) of each road leg, in itinerary order."""
        return [
            (self.departure(self.stops[number - 2]), self.arrival(self.stops[number - 1]))
            for kind, number, *_ in self.expected_lines()
            if kind == "road"
        ]

    def expected_lines(self) -> list[tuple[str, int, str, str | None, str | None]]:
        """(kind, stop number, item id, level, reason) of each line, in itinerary order: the road leg into a row, then
        the row's own line."""
        lines: list[tuple[str, int, str, str | None, str | None]] = []
        for number, stop in enumerate(self.stops, start=1):
            if stop.kind != "retrace" and number > 1 and self.departure(self.stops[number - 2]) != self.arrival(stop):
                lines.append(("road", number, stop.item_id, stop.leg_confidence, stop.leg_reason))
            if stop.kind == "track":
                lines.append(("track", number, stop.item_id, None, None))
            if stop.kind == "retrace":
                lines.append(("retrace", number, stop.item_id, stop.confidence, stop.reason))
        return lines


def seen_lines(answer: RunGeometry) -> list[tuple[str, int, str, str | None, str | None]]:
    return [(line.kind, line.stop, line.item_id, line.level, line.reason) for line in answer.lines]


@given(itinerary=itineraries())
@settings(max_examples=60, deadline=None)
def test_lines_follow_the_itinerary_and_tracks_run_the_way_they_are_driven(
    itinerary: tuple[bool, tuple[Row, ...]],
) -> None:
    trip = Trip(*itinerary)
    answer = trip.service(Engine()).geometry(RUN_ID)

    assert seen_lines(answer) == trip.expected_lines()
    for line in answer.lines:
        stop = trip.stops[line.stop - 1]
        if line.kind == "road":
            previous = trip.stops[line.stop - 2]
            assert (line.points[0], line.points[-1]) == (trip.departure(previous), trip.arrival(stop))
            assert line.geometry == "available"
        if line.kind == "track":
            assert line.points == trip.tracks[line.item_id]  # entry to exit, stored order
        if line.kind == "retrace":
            assert line.points == tuple(reversed(trip.tracks[line.item_id]))  # exit back to entry


@example(count=1_500)
@example(count=1_501)
@given(count=st.integers(2, 4_000))
@settings(max_examples=40, deadline=None)
def test_a_long_track_is_thinned_to_at_most_1500_points_keeping_first_and_last(count: int) -> None:
    trip = Trip(False, (Row("track", count),))
    (track_line,) = [line for line in trip.service(Engine()).geometry(RUN_ID).lines if line.kind == "track"]
    stored = list(trip.tracks["track-2"])

    assert len(track_line.points) <= 1_500
    assert count <= 1_500 or len(track_line.points) >= 750  # thinned, never to a mere handful
    assert (track_line.points[0], track_line.points[-1]) == (stored[0], stored[-1])
    positions = [stored.index(point) for point in track_line.points]
    assert positions == sorted(set(positions))  # the stored points, in their order
    assert count > 1_500 or list(track_line.points) == stored  # a track that fits is drawn as stored


@given(itinerary=itineraries())
@settings(max_examples=40, deadline=None)
def test_road_legs_are_straight_and_unavailable_when_the_road_map_is_not_the_one_the_run_used(
    itinerary: tuple[bool, tuple[Row, ...]],
) -> None:
    trip = Trip(*itinerary)
    engine = Engine()
    answer = trip.service(engine, identity=("rebuilt-map", ROAD_MAP[1])).geometry(RUN_ID)

    assert engine.asked == []
    roads = [line for line in answer.lines if line.kind == "road"]
    assert all(line.geometry == "unavailable" and len(line.points) == 2 for line in roads)
    assert all(line.geometry == "available" for line in answer.lines if line.kind != "road")
    assert trip.events.fields_of("plan.run.geometry_served")[0]["unavailable"] == len(roads)


@given(itinerary=itineraries(), fail_from=st.integers(1, 6))
@settings(max_examples=60, deadline=None)
def test_the_answer_stays_whole_when_the_engine_fails_part_way(
    itinerary: tuple[bool, tuple[Row, ...]], fail_from: int
) -> None:
    trip = Trip(*itinerary)
    engine = Engine(fail_from=fail_from, legs=trip.road_legs())
    answer = trip.service(engine).geometry(RUN_ID)

    assert seen_lines(answer) == trip.expected_lines()
    roads = [line for line in answer.lines if line.kind == "road"]
    fetched = [line for line in roads if line.geometry == "available"]
    fetched_count = min(fail_from - 1, len(roads))
    assert [line.stop for line in fetched] == [line.stop for line in roads[:fetched_count]]  # the first legs, no other
    assert sorted(engine.answered, key=repr) == sorted(trip.road_legs()[:fetched_count], key=repr)  # each asked once
    assert len(engine.asked) >= fetched_count
    assert all(len(line.points) == 2 for line in roads if line.geometry == "unavailable")
    served = trip.events.fields_of("plan.run.geometry_served")[0]
    assert (served["legs"], served["legs_fetched"], served["unavailable"]) == (
        len(roads),
        len(fetched),
        len(roads) - len(fetched),
    )
    assert engine.most_at_once <= 2


@given(itinerary=itineraries())
@settings(max_examples=40, deadline=None)
def test_markers_number_the_stops_and_mark_where_each_trail_is_entered_and_left(
    itinerary: tuple[bool, tuple[Row, ...]],
) -> None:
    round_trip, _ = itinerary
    trip = Trip(*itinerary)
    markers = trip.service(Engine()).geometry(RUN_ID).markers
    last = len(trip.stops)

    for marker in markers:  # each carries its stop's identity and place
        stop = trip.stops[marker.stop - 1]
        assert (marker.item_id, marker.name) == (stop.item_id, stop.name)
        assert marker.point == (trip.departure(stop) if marker.marker == "exit" else trip.arrival(stop))
    numbered = sorted(
        [m.stop for m in markers if m.marker in {"stop", "start", "end", "start_end"}]
        + [m.end_stop for m in markers if m.end_stop is not None]
    )
    retraces = {number for number, stop in enumerate(trip.stops, start=1) if stop.kind == "retrace"}
    assert numbered == [number for number in range(1, last + 1) if number not in retraces]
    kinds = [m.marker for m in markers if m.marker in {"start", "end", "start_end"}]
    assert kinds == (["start_end"] if round_trip else ["start", "end"])
    for number, stop in enumerate(trip.stops, start=1):
        if stop.kind == "track":
            placed = {m.marker: m.point for m in markers if m.stop == number and m.marker in {"entry", "exit"}}
            assert placed == {"entry": stop.entry, "exit": stop.exit}


class UnreadableFileStore(InMemoryFileStore):
    def __init__(self, failure: OSError) -> None:
        super().__init__()
        self._failure = failure

    def read_canonical_points(self, track_id: str, direction_version: int) -> bytes | CanonicalPointsMissing:
        raise self._failure


@pytest.mark.parametrize(
    "cause", ["missing", "permission", "is_a_directory", "invalid", "one_point", "no_direction_version"]
)
def test_a_track_whose_points_cannot_be_read_is_the_chord_marked_unavailable_with_its_retrace(cause: str) -> None:
    trip = Trip(
        False, (Row("track", 5), Row("retrace")), direction_version=None if cause == "no_direction_version" else 2
    )
    if cause == "missing":
        trip.files = InMemoryFileStore()
    elif cause == "permission":
        trip.files = UnreadableFileStore(PermissionError("denied"))
    elif cause == "is_a_directory":
        trip.files = UnreadableFileStore(IsADirectoryError("a folder"))
    elif cause == "invalid":
        trip.files.files = {path: b"{not points" for path in trip.files.files}
    elif cause == "one_point":
        trip.files.files = {path: canonical_points_file([TrackPoint(at(1))]) for path in trip.files.files}
    track = trip.stops[1]
    assert track.entry is not None and track.exit is not None

    answer = trip.service(Engine()).geometry(RUN_ID)

    drawn = {line.kind: line for line in answer.lines if line.kind != "road"}
    assert (drawn["track"].geometry, drawn["track"].points) == ("unavailable", (track.entry, track.exit))
    assert (drawn["retrace"].geometry, drawn["retrace"].points) == ("unavailable", (track.exit, track.entry))
    assert all(line.geometry == "available" for line in answer.lines if line.kind == "road")


def test_a_failed_run_and_an_unknown_run_have_nothing_to_draw_and_each_answer_is_logged() -> None:
    trip = Trip(False, ())
    trip.planning.runs.append(  # bypass: one failed run is the whole rule, there is no input to vary
        NewPlanRun(
            id="failed-1",
            project_id="project-1",
            number=5,
            status="failed",
            failure_reason="unreachable",
            created_at=datetime(2026, 11, 17, tzinfo=UTC),
            revision=1,
            provider_id=ROAD_MAP[0],
            objective="distance",
            inputs={},
            stops=(),
            profile=ROAD_MAP[1],
        )
    )
    service = trip.service(Engine())

    with pytest.raises(RunHasNoRouteError):
        service.geometry("failed-1")
    with pytest.raises(PlanRunNotFoundError):
        service.geometry("no-such-run")
    assert trip.events.fields_of("plan.run.geometry_served") == []
    service.geometry(RUN_ID)
    (served,) = trip.events.fields_of("plan.run.geometry_served")
    assert (served["plan_run_id"], served["legs"], served["legs_fetched"], served["unavailable"]) == (RUN_ID, 1, 1, 0)
    assert isinstance(served["served_ms"], int)

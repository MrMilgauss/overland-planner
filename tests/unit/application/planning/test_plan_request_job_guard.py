"""The guard wired into the plan job (ADR-009, ADR-015, carry-overs of 04-02 and 04-04): no plan is stored unchecked.

Driving ports: `PlanRequestJob.run` and, for the job's end, `PlanJobRegistry`. Driven ports: `PlanningUnitOfWork`,
`RoutingProvider`, `TourSolver` (scripted), `FileStore`, `EventLog`. Removing the guard from the job fails these tests.
Observable universe: `plan_runs`, `items`, `projects` as planning reads them and `files` as the store holds them.
Test Budget: 5 behaviors (a passing plan is stored and logged ok; a changed or vanished file stores one Failed run; a
solver's broken order ends the same way, job done; the size of a real track; canonical file round trip) x 2 = 10;
5 used.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cache
from itertools import permutations
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import canonical_points_file, parse_canonical_points_file
from overland_planner.application.planning.facade import PlanJobRegistry, PlanRequestJob, StoredRun
from overland_planner.application.ports.plan_run_repository import NewPlanRun
from overland_planner.application.ports.tour_solver import TourFound, TourOutcome
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.catalog.track_stats_calculator import TrackStats, TrackStatsCalculator
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta
from tests.unit.application.planning.planning_doubles import InMemoryPlanning, RecordingRoadMap, job_when_ended
from tests.unit.application.planning.scripted_tour_solver import ScriptedTourSolver
from tests.unit.domain.planning.trips import PROJECT, Trip, track_points, trips

UNIVERSE = {"plan_runs", "items", "projects", "files"}
REASON = "internal_invariant_violation"
BUDGET = 500
VIOLATION_FIELDS = {"plan_run_id", "check", "detail"}
BIG_TRACK_POINTS = 23_295
BIG_TRACK_M = 224_800.0
METRES_PER_DEGREE_OF_LATITUDE = 111_195.08


class _Progress:
    def __init__(self) -> None:
        self.facts: dict[str, object] = {}

    def enter(self, state: str) -> None:
        assert state in {"computing_legs", "solving", "finalising"}, f"not a state of the job's work: {state}"

    def note(self, **facts: object) -> None:
        self.facts.update(facts)

    @contextmanager
    def solver_slot(self) -> Iterator[None]:
        yield


@dataclass
class Harness:
    """The real job over the doubles of its driven ports."""

    planning: InMemoryPlanning
    files: InMemoryFileStore
    job: PlanRequestJob
    clock: FakeClock
    log: RecordingEventLog = field(default_factory=RecordingEventLog)

    def view(self) -> dict[str, Any]:
        snapshot = self.planning.snapshots[PROJECT]
        return {
            "plan_runs": tuple(_row(run) for run in self.planning.runs),
            "items": tuple(item.id for item in snapshot.items),
            "projects": (PROJECT, self.planning.stamps[PROJECT], snapshot.start_item_id, snapshot.end_item_id),
            "files": tuple(sorted(self.files.files.items())),
        }

    def run(self) -> StoredRun:
        return self.job.run(PROJECT, _Progress())


def _row(run: NewPlanRun) -> tuple[Any, ...]:
    return (run.number, run.status, run.failure_reason, tuple(stop.item_id for stop in run.stops))


def _harness(
    snapshot: ProjectSnapshot,
    leg_m: dict[tuple[Coordinate, Coordinate], int],
    files: InMemoryFileStore,
    outcome: TourOutcome | None = None,
) -> Harness:
    planning = InMemoryPlanning()
    planning.add_project(PROJECT, snapshot)
    clock, log = FakeClock(), RecordingEventLog()
    solver = ScriptedTourSolver(outcome)
    job = PlanRequestJob(planning.unit_of_work, LegResolver(RecordingRoadMap(leg_m)), solver, BUDGET, clock, log, files)
    return Harness(planning, files, job, clock, log)


def _harness_of(trip: Trip, outcome: TourOutcome | None = None) -> Harness:
    files = InMemoryFileStore()
    trip.seed_canonical_files(files)
    return _harness(trip.snapshot, trip.leg_m, files, outcome)


def _assert_one_failed_run_only(harness: Harness, before: dict[str, Any], stored: StoredRun, check: str) -> None:
    """A failing plan changes only `plan_runs`, with one Failed row, and the log names the broken rule."""
    assert_state_delta(before, harness.view(), UNIVERSE, {"plan_runs": gained((1, "failed", REASON, ()))}, strict=True)
    assert stored == StoredRun(harness.planning.runs[-1].id, REASON)
    violations = harness.log.fields_of("invariant.violation")
    assert len(violations) == 1
    assert set(violations[0]) == VIOLATION_FIELDS
    assert (violations[0]["plan_run_id"], violations[0]["check"]) == (stored.plan_run_id, check)
    assert violations[0]["detail"], "the event says what is wrong"
    completed = harness.log.fields_of("plan.run.completed")
    assert [(c["status"], c["failure_reason"], c["invariants"]) for c in completed] == [("failed", REASON, "violated")]


@settings(deadline=None)
@given(trip=trips(), data=st.data())
def test_a_passing_plan_is_stored_ready_and_logged_with_invariants_ok(trip: Trip, data: st.DataObject) -> None:
    visited = data.draw(st.permutations([item.id for item in trip.items]), label="order")
    harness = _harness_of(trip, TourFound((trip.start.id, *visited, trip.end.id)))
    before = harness.view()

    stored = harness.run()

    row = (1, "ready", None, (trip.start.id, *visited, trip.end.id))
    assert_state_delta(before, harness.view(), UNIVERSE, {"plan_runs": gained(row)}, strict=True)
    assert stored.reason is None
    assert harness.log.fields_of("invariant.violation") == []
    assert [c["invariants"] for c in harness.log.fields_of("plan.run.completed")] == ["ok"]


def _damages(track: TrackItem) -> st.SearchStrategy[bytes | None]:
    """What can happen to a canonical file; `None` is a file that vanished."""
    points = track_points(track.entry, track.exit, track.point_count)
    return st.one_of(
        st.just(None),
        st.sampled_from([b"", b"not json", b"[]", b'{"points":{}}', b'{"points":[[1]]}', b'{"points":[["a",7.0,0]]}']),
        st.just(canonical_points_file(points[:-1])),
        st.integers(0, len(points) - 1).map(lambda at: canonical_points_file(_altered(points, at, "latitude"))),
        st.integers(0, len(points) - 1).map(lambda at: canonical_points_file(_altered(points, at, "elevation"))),
    )


def _altered(points: tuple[TrackPoint, ...], at: int, what: str) -> tuple[TrackPoint, ...]:
    """The sequence with one point different and nothing else: same count, and usually the same ends."""
    point = points[at]
    coordinate = point.coordinate
    changed = {
        "latitude": TrackPoint.at(coordinate.latitude + 0.00001, coordinate.longitude, point.elevation_m),
        "longitude": TrackPoint.at(coordinate.latitude, coordinate.longitude + 0.00001, point.elevation_m),
        "elevation": TrackPoint(coordinate, (point.elevation_m or 0.0) + 1.0),
    }[what]
    return (*points[:at], changed, *points[at + 1 :])


@settings(deadline=None)
@given(trip=trips().filter(lambda trip: bool(trip.tracks())), data=st.data())
def test_a_track_whose_file_changed_or_vanished_stores_one_failed_run_and_no_itinerary(
    trip: Trip, data: st.DataObject
) -> None:
    track = data.draw(st.sampled_from(trip.tracks()), label="track")
    damage = data.draw(_damages(track), label="damage")
    harness = _harness_of(trip)
    if damage is None:
        harness.files.lose_canonical_points(track.id, track.direction_version)
    else:
        harness.files.keep_canonical_points(track.id, track.direction_version, damage)
    before = harness.view()

    stored = harness.run()

    _assert_one_failed_run_only(harness, before, stored, "HC-5")
    assert track.id in str(harness.log.fields_of("invariant.violation")[0]["detail"])


def _orders_the_solver_should_not_give(trip: Trip) -> st.SearchStrategy[tuple[tuple[str, ...], str]]:
    start, end = trip.start.id, trip.end.id
    visited = tuple(item.id for item in trip.items)
    orders = [
        ((start, "no-such-item", *visited, end), "HC-3"),
        (("no-such-item", *visited, end), "HC-2"),
        ((start, *visited, "no-such-item"), "HC-2"),
        ((start, end, *visited, end), "HC-3"),
    ]
    if visited:
        orders.append(((start, *visited[1:], end), "HC-3"))
        orders.append(((start, visited[0], *visited, end), "HC-3"))
    return st.sampled_from(orders)


@settings(deadline=None)
@given(trip=trips(), data=st.data())
def test_a_broken_order_from_the_solver_ends_the_job_done_with_a_failed_run_never_a_failed_job(
    trip: Trip, data: st.DataObject
) -> None:
    order, check = data.draw(_orders_the_solver_should_not_give(trip), label="order")
    harness = _harness_of(trip, TourFound(order))
    before = harness.view()
    registry = PlanJobRegistry(harness.clock, harness.job, harness.log)

    job_id = registry.start(PROJECT)
    assert job_id is not None
    job = job_when_ended(registry, job_id)

    assert (job.state, job.reason, job.message) == ("done", REASON, None)
    assert job.plan_run_id is not None
    _assert_one_failed_run_only(harness, before, StoredRun(job.plan_run_id, REASON), check)
    finished = harness.log.fields_of("plan.job.finished")
    assert [(f["terminal_state"], f["reason"], f["plan_run_id"]) for f in finished] == [
        ("done", REASON, job.plan_run_id)
    ]


@cache
def _big_points() -> tuple[TrackPoint, ...]:
    """Same size as Marco's real recording (D198: that file stays out of the repository), straight north."""
    step = BIG_TRACK_M / (BIG_TRACK_POINTS - 1) / METRES_PER_DEGREE_OF_LATITUDE
    return tuple(TrackPoint.at(44.0 + i * step, 7.0, 1500.0) for i in range(BIG_TRACK_POINTS))


@cache
def _big_trip() -> tuple[ProjectSnapshot, dict[tuple[Coordinate, Coordinate], int], TrackItem]:
    points = _big_points()
    stats = TrackStatsCalculator().calculate(points)
    assert isinstance(stats, TrackStats)
    assert abs(stats.length_m - BIG_TRACK_M) < 100, f"the generated track is {stats.length_m} m"
    track = TrackItem(
        id="assietta-sized",
        project_id=PROJECT,
        name="Strada dell'Assietta",
        description=None,
        original_sha256="original",
        canonical_sha256=hashlib.sha256(canonical_points_file(points)).hexdigest(),
        direction_version=1,
        point_count=len(points),
        entry=stats.entry.coordinate,
        exit=stats.exit.coordinate,
        length_m=stats.length_m,
    )
    home = PoiItem(id="home", project_id=PROJECT, name="Casa", location=track.entry)
    leg_m = {pair: 300_000 for pair in permutations((track.entry, track.exit), 2)}
    return ProjectSnapshot(home.id, home.id, (home, track)), leg_m, track


def _big_harness(content: bytes) -> Harness:
    snapshot, leg_m, track = _big_trip()
    files = InMemoryFileStore()
    files.keep_canonical_points(track.id, track.direction_version, content)
    return _harness(snapshot, leg_m, files)


@settings(deadline=None, max_examples=20)
@given(
    at=st.integers(0, BIG_TRACK_POINTS - 1),
    what=st.sampled_from(("latitude", "longitude", "elevation")),
)
def test_a_track_of_real_size_passes_and_one_altered_point_anywhere_fails(at: int, what: str) -> None:
    points = _big_points()
    assert _big_harness(canonical_points_file(points)).run().reason is None
    harness = _big_harness(canonical_points_file(_altered(points, at, what)))
    before = harness.view()

    stored = harness.run()

    _assert_one_failed_run_only(harness, before, stored, "HC-5")


coordinates = st.builds(
    TrackPoint.at,
    st.floats(-90, 90, allow_nan=False),
    st.floats(-180, 180, allow_nan=False),
    st.none() | st.floats(-500, 9000, allow_nan=False),
)


@given(points=st.lists(coordinates, max_size=50))
def test_the_parser_reads_back_what_the_encoder_wrote(points: list[TrackPoint]) -> None:
    content = canonical_points_file(points)

    assert parse_canonical_points_file(content) == tuple(points)
    assert canonical_points_file(parse_canonical_points_file(content)) == content

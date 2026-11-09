"""The fingerprint memo of the plan job (ADR-014 section 5, FR-5.6, D74, ADR-015 line 21, ADR-009 after a hit).

Driving ports: `PlanJobRegistry` (start and poll) over the real `PlanRequestJob` with a `FingerprintMemo`, and
`PlanRequestJob.run`. Driven ports: `PlanningUnitOfWork`, `RoutingProvider`, `TourSolver` (a script that proposes a
drawn order, so a reused order is told apart from a fresh one), `FileStore`, `EventLog`.
Observable universe: `plan_runs` as the database double holds them (order, totals, `memo_hit`) and `solver_calls`.
Test Budget: 2 behaviors (the solver is asked iff no ready run of the project has the inputs' fingerprint or
`ignore_memo` is set, otherwise the run reuses that order with recomputed totals and says `memo_hit`; a reused order is
judged by the guard, a violation stores a Failed run that is never a memo source) x 2 = 4; 2 used.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace
from typing import Any

from hypothesis import example, given, settings
from hypothesis import strategies as st

from overland_planner.application.planning.facade import FingerprintMemo, PlanJobRegistry, PlanRequestJob
from overland_planner.application.ports.plan_run_repository import NewPlanRun
from overland_planner.application.ports.project_snapshot_reader import ProjectStamp
from overland_planner.application.ports.tour_solver import TourFound, TourNoRoute, TourOutcome, TourTimedOut
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.catalog.project import DEFAULT_OFFROAD_SPEED, OffroadSpeed
from overland_planner.domain.planning.plan_run import Totals
from overland_planner.domain.planning.plan_run_assembler import PlanRunAssembler
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.solver_model_builder import TourModel
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta, set_to, unchanged
from tests.unit.application.planning.planning_doubles import (
    DEFAULT_STAMP,
    InMemoryPlanning,
    RecordingRoadMap,
    job_when_ended,
)
from tests.unit.domain.planning.trips import POINT_PAIRS, POINTS, PROJECT, Trip, road_time_s, trips

UNIVERSE = {"plan_runs", "solver_calls"}
OTHER_PROJECT = "q"
BUDGET = 500
IDENTITY = "ortools==9.15.6755;PATH_CHEAPEST_ARC;GUIDED_LOCAL_SEARCH"
REASON = "internal_invariant_violation"
INPUTS = ("same", "item", "anchor", "leg distance", "road map", "objective", "budget", "solver identity")


class _ProposingSolver:
    """Answers each solve with the next scripted answer. A `TourFound` script holds the trip's items in the order to
    propose; a place the Calculate added follows them."""

    def __init__(self) -> None:
        self.answers: list[TourOutcome] = []
        self.calls = 0

    def probe(self) -> Any:
        raise AssertionError("the plan job never probes the solver")

    def solve(self, model: TourModel, budget: int) -> TourOutcome:
        self.calls += 1
        assert self.answers, "the solver was asked although the memo had the order"
        answer = self.answers.pop(0)
        if isinstance(answer, TourFound):
            nodes = model.node_item_ids
            return TourFound((nodes[0], *_proposed(answer.order, nodes[1:-1]), nodes[-1]))
        return answer


def _proposed(order: tuple[str, ...], visited: tuple[str, ...]) -> tuple[str, ...]:
    return (*order, *(item_id for item_id in visited if item_id not in order))


@dataclass(frozen=True)
class Calculate:
    project: str
    changed: str
    ignore_memo: bool
    speed: OffroadSpeed
    answer: TourOutcome


@dataclass
class Desk:
    """Two projects with the same trip, planned by the real job with a memo over the doubles of its driven ports."""

    trip: Trip
    planning: InMemoryPlanning = field(default_factory=InMemoryPlanning)
    files: InMemoryFileStore = field(default_factory=InMemoryFileStore)
    solver: _ProposingSolver = field(default_factory=_ProposingSolver)
    log: RecordingEventLog = field(default_factory=RecordingEventLog)
    clock: FakeClock = field(default_factory=FakeClock)

    def __post_init__(self) -> None:
        self.trip.seed_canonical_files(self.files)

    def view(self) -> dict[str, Any]:
        return {"plan_runs": tuple(_row(run) for run in self.planning.runs), "solver_calls": self.solver.calls}

    def job(self, changed: str) -> tuple[PlanRequestJob, LegTable]:
        """The job and the road legs it gets, with the one input `changed` (or none)."""
        shift = 1 if changed == "leg distance" else 0
        leg_m = {pair: metres + shift for pair, metres in self.trip.leg_m.items()}
        road_map = RecordingRoadMap(leg_m)
        if changed == "road map":
            road_map.provider_id = "another-road-map"
        job = PlanRequestJob(
            self.planning.unit_of_work,
            LegResolver(road_map),
            self.solver,
            BUDGET + 1 if changed == "budget" else BUDGET,
            self.clock,
            self.log,
            self.files,
            memo=FingerprintMemo(IDENTITY + "-next" if changed == "solver identity" else IDENTITY),
        )
        legs = LegTable(RoadLeg(origin, destination, m, road_time_s(m)) for (origin, destination), m in leg_m.items())
        return job, legs

    def project_as(self, project: str, changed: str, speed: OffroadSpeed) -> ProjectSnapshot:
        snapshot = replace(self.trip.snapshot, offroad_speed=speed)
        here = self.trip.start.location
        if changed == "item":
            snapshot = replace(snapshot, items=(*snapshot.items, _place("one-more-place", here)))
        if changed == "anchor":
            snapshot = replace(
                snapshot, start_item_id="another-start", items=(*snapshot.items, _place("another-start", here))
            )
        stamp = ProjectStamp(DEFAULT_STAMP.revision, "time" if changed == "objective" else DEFAULT_STAMP.objective)
        self.planning.add_project(project, snapshot, stamp)
        return snapshot


def _place(item_id: str, location: Coordinate) -> PoiItem:
    return PoiItem(id=item_id, project_id=PROJECT, name="Rifugio", location=location)


def _row(run: NewPlanRun) -> tuple[Any, ...]:
    order = tuple(stop.item_id for stop in run.stops)
    return (run.project_id, run.number, run.status, run.failure_reason, order, run.totals, run.memo_hit)


ANSWERS = st.one_of(st.just(TourNoRoute()), st.just(TourTimedOut()))


@st.composite
def calculates(draw: st.DrawFn, trip: Trip) -> Calculate:
    visited = tuple(item.id for item in trip.items)
    found = st.permutations(list(visited)).map(lambda order: TourFound(tuple(order)))
    return Calculate(
        project=draw(st.sampled_from((PROJECT, OTHER_PROJECT))),
        changed=draw(st.sampled_from(INPUTS)),
        ignore_memo=draw(st.booleans()),
        speed=draw(st.floats(0.5, 120.0).map(OffroadSpeed)),
        answer=draw(st.one_of(found, found, ANSWERS)),
    )


def _round_trip_with_nothing_to_visit() -> Trip:
    start = PoiItem(id="start", project_id=PROJECT, name="Casa Marco", location=POINTS[0])
    leg_m = {pair: metres for metres, pair in enumerate(POINT_PAIRS, start=1)}
    legs = LegTable(RoadLeg(origin, destination, m, road_time_s(m)) for (origin, destination), m in leg_m.items())
    snapshot = ProjectSnapshot(start.id, start.id, (start,), DEFAULT_OFFROAD_SPEED)
    return Trip(snapshot, legs, leg_m, start, start, ())


def _press(answer: TourOutcome) -> Calculate:
    return Calculate(PROJECT, "same", ignore_memo=False, speed=OffroadSpeed(1.0), answer=answer)


PRESSES = trips().flatmap(lambda trip: st.tuples(st.just(trip), st.lists(calculates(trip), min_size=1, max_size=8)))


@settings(deadline=None, max_examples=60)
@given(case=PRESSES)
@example(case=(_round_trip_with_nothing_to_visit(), [_press(TourFound(())), _press(TourNoRoute())]))  # an empty order
def test_the_solver_is_asked_iff_no_ready_run_of_the_project_has_the_fingerprint_or_the_memo_is_ignored(
    case: tuple[Trip, list[Calculate]],
) -> None:
    trip, presses = case
    desk = Desk(trip)
    memo: dict[tuple[str, str], tuple[str, ...]] = {}  # (project, changed input) -> order of its latest ready run
    for press in presses:
        snapshot = desk.project_as(press.project, press.changed, press.speed)
        job, legs = desk.job(press.changed)
        desk.solver.answers = [press.answer]
        reused = None if press.ignore_memo else memo.get((press.project, press.changed))
        registry = PlanJobRegistry(desk.clock, job, desk.log)
        before = desk.view()

        job_id = registry.start(press.project, ignore_memo=press.ignore_memo)
        assert job_id is not None
        polled = job_when_ended(registry, job_id)

        visiting = tuple(item.id for item in snapshot.visited_items())
        fresh = _proposed(press.answer.order, visiting) if isinstance(press.answer, TourFound) else None
        order = reused if reused is not None else fresh
        number = sum(1 for row in before["plan_runs"] if row[0] == press.project) + 1
        if order is None:
            row = (press.project, number, "failed", getattr(press.answer, "reason", None), (), None, False)
        else:
            totals = Totals.of(PlanRunAssembler(snapshot, legs).assemble(order))
            stops = (snapshot.start_item_id, *order, snapshot.end_item_id)
            row = (press.project, number, "ready", None, stops, totals, reused is not None)
            memo[press.project, press.changed] = order
        expected = {
            "plan_runs": gained(row),
            "solver_calls": unchanged() if reused is not None else set_to(before["solver_calls"] + 1),
        }
        assert_state_delta(before, desk.view(), UNIVERSE, expected, strict=True)
        hit = reused is not None
        assert (polled.state, polled.memo_hit, polled.ignore_memo) == ("done", hit, press.ignore_memo)
        assert desk.log.fields_of("plan.run.completed")[-1]["memo_hit"] is hit
        assert desk.log.fields_of("plan.job.finished")[-1]["memo_hit"] is hit


@settings(deadline=None, max_examples=30)
@given(trip=trips().filter(lambda trip: bool(trip.tracks())), data=st.data())
def test_a_reused_order_is_judged_by_the_guard_and_a_failed_run_is_never_a_memo_source(
    trip: Trip, data: st.DataObject
) -> None:
    desk = Desk(trip)
    visited = tuple(data.draw(st.permutations([item.id for item in trip.items]), label="order"))
    snapshot = desk.project_as(PROJECT, "same", trip.snapshot.offroad_speed)
    job, legs = desk.job("same")
    desk.solver.answers = [TourFound(visited)]
    job.run(PROJECT, _Progress())
    track = data.draw(st.sampled_from(trip.tracks()), label="track")
    kept = desk.files.read_canonical_points(track.id, track.direction_version)
    assert isinstance(kept, bytes)
    stops = (snapshot.start_item_id, *visited, snapshot.end_item_id)
    totals = Totals.of(PlanRunAssembler(snapshot, legs).assemble(visited))

    for damaged, row in (
        (True, (PROJECT, 2, "failed", REASON, (), None, True)),
        (False, (PROJECT, 3, "ready", None, stops, totals, True)),
    ):
        desk.files.keep_canonical_points(track.id, track.direction_version, b"not json" if damaged else kept)
        before = desk.view()

        job.run(PROJECT, _Progress())

        expected = {"plan_runs": gained(row), "solver_calls": unchanged()}
        assert_state_delta(before, desk.view(), UNIVERSE, expected, strict=True)
    assert [fields["check"] for fields in desk.log.fields_of("invariant.violation")] == ["HC-5"]

    desk.solver.answers = [TourFound(visited)]
    before = desk.view()
    job.run(PROJECT, _Progress(), ignore_memo=True)
    fresh = (PROJECT, 4, "ready", None, stops, totals, False)
    expected = {"plan_runs": gained(fresh), "solver_calls": set_to(before["solver_calls"] + 1)}
    assert_state_delta(before, desk.view(), UNIVERSE, expected, strict=True)


class _Progress:
    def enter(self, state: str) -> None:
        return None

    def note(self, **facts: object) -> None:
        return None

    def solver_slot(self) -> AbstractContextManager[None]:
        return nullcontext()

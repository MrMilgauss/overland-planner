"""The plan job (US-02b, brief section 8, ADR-015, D122): Calculate answers at once; the job ends in one terminal state.

Driving ports: `PlanRequestService`, `PlanJobRegistry` (polling) and `PlanRunQueries` from the planning facade, over the
real `PlanRequestJob` and `LegResolver`. Driven ports: `PlanningUnitOfWork`, `RoutingProvider`, `TourSolver` (scripted),
`Clock` (`FakeClock`, which never moves by itself) and `EventLog`.
Observable universe: `plan_runs` as the database double holds them, `items` and `projects` as planning reads them.
Test Budget: 4 behaviors (any solver outcome ends the job in one terminal state with at most one stored run; the request
answers before the job is done and no run is named until stored; finished jobs are kept for 10 minutes and running ones
always; each job logs its events) x 2 = 8; 5 used.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass
from typing import Any

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from overland_planner.application.planning.facade import (
    PlanJobRegistry,
    PlanJobView,
    PlanRequestJob,
    PlanRequestService,
    PlanRunQueries,
)
from overland_planner.application.platform.facade import HealthService
from overland_planner.application.ports.plan_run_repository import NewPlanRun
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.tour_solver import (
    TourFound,
    TourNoRoute,
    TourOptimizerFailed,
    TourTimedOut,
)
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder
from tests.common.catalog_fakes import RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.predicates import gained
from tests.common.solver_fakes import SolveAbandonedError
from tests.common.state_delta import assert_state_delta
from tests.unit.application.planning.planning_doubles import DEFAULT_STAMP, Gate, InMemoryPlanning, RecordingRoadMap
from tests.unit.application.planning.scripted_tour_solver import Script, ScriptedTourSolver
from tests.unit.domain.planning.trips import PROJECT, Trip, left_at, reached_at, trips

UNIVERSE = {"plan_runs", "items", "projects"}
BUDGET = 500
KEPT_FOR_S = 600.0
WAIT_S = 30.0
POLL_S = 0.0005
FAILED_MESSAGE = "The plan could not be calculated - nothing was changed"
TERMINAL_STATES = {"done", "failed", "refused", "cancelled", "timed_out"}
KPI_FIELDS = {  # docs/product/kpi-contracts.yaml, plan.job.finished
    "job_id",
    "project_id",
    "terminal_state",
    "plan_run_id",
    "items_included",
    "legs_total",
    "legs_new",
    "legs_cached",
    "points_located",
    "points_new",
    "second_pass_pairs",
    "retried",
    "memo_hit",
    "ignore_memo",
    "stage_ms",
    "solver_solutions",
    "incumbents",
    "reproducible",
    "not_fully_optimised_reason",
    "unconfirmed_legs",
    "retraces",
    "provider_id",
    "elapsed_ms",
}
FIELDS_OF_LATER_SLICES = KPI_FIELDS - {
    "job_id",
    "project_id",
    "terminal_state",
    "plan_run_id",
    "items_included",
    "legs_total",
    "provider_id",
    "elapsed_ms",
}
RUN_FIELDS = {"plan_run_id", "number", "status", "failure_reason", "report_items", "project_items", "invariants"}


@dataclass(frozen=True)
class Plan:
    trip: Trip
    script: Script
    earlier_runs: int


@dataclass
class Planner:
    """The real plan job and its services over the doubles of the driven ports. `held` is the gate the job stops at."""

    planning: InMemoryPlanning
    solver: ScriptedTourSolver
    clock: FakeClock
    log: RecordingEventLog
    registry: PlanJobRegistry
    service: PlanRequestService
    queries: PlanRunQueries
    held: Gate

    def view(self) -> dict[str, Any]:
        snapshot = self.planning.snapshots[PROJECT]
        stamp = self.planning.stamps[PROJECT]
        return {
            "plan_runs": tuple(_row(run) for run in self.planning.runs if run.project_id == PROJECT),
            "items": tuple(item.id for item in snapshot.items),
            "projects": (PROJECT, stamp, snapshot.start_item_id, snapshot.end_item_id),
        }

    def poll(self, job_id: str) -> PlanJobView:
        job = self.registry.get(job_id)
        assert job is not None, f"job {job_id} is not known"
        return job

    def wait_until_ended(self, job_id: str) -> PlanJobView:
        deadline = time.monotonic() + WAIT_S
        job = self.poll(job_id)
        while job.state not in TERMINAL_STATES:
            assert time.monotonic() < deadline, f"the job did not end: {job}"
            time.sleep(POLL_S)
            job = self.poll(job_id)
        return job

    def wait_until_held(self) -> None:
        assert self.held.reached.wait(WAIT_S), "the job never reached the gate"


class _HeldBehindThePreCheck(Gate):
    """Lets the request's own pre-check read through and holds the job's snapshot read."""

    def __init__(self) -> None:
        super().__init__(held=True)
        self._reads = 0

    def passing(self) -> None:
        self._reads += 1
        if self._reads > 1:
            super().passing()


def _planner(trip: Trip, script: Script = None, *, held_at: str | None = None) -> Planner:
    gates = {
        "queued": _HeldBehindThePreCheck() if held_at == "queued" else Gate(),
        "computing_legs": Gate(held=held_at == "computing_legs"),
        "solving": Gate(held=held_at == "solving"),
        "finalising": Gate(held=held_at == "finalising"),
    }
    planning = InMemoryPlanning(reading=gates["queued"], storing=gates["finalising"])
    planning.add_project(PROJECT, trip.snapshot)
    road_map = RecordingRoadMap(trip.leg_m, gate=gates["computing_legs"])
    solver = ScriptedTourSolver(script, gate=gates["solving"])
    clock = FakeClock()
    log = RecordingEventLog()
    job = PlanRequestJob(planning.unit_of_work, LegResolver(road_map), solver, BUDGET, clock, log)
    registry = PlanJobRegistry(clock, job, log)
    health = HealthService({"tour_solver": ProbeResult("ok")})
    service = PlanRequestService(planning.unit_of_work, health, log, registry)
    queries = PlanRunQueries(planning.unit_of_work)
    return Planner(planning, solver, clock, log, registry, service, queries, gates.get(held_at or "", Gate()))


def _row(run: NewPlanRun) -> tuple[Any, ...]:
    return (
        run.number,
        run.status,
        run.failure_reason,
        tuple((stop.item_id, stop.kind, stop.leg_km) for stop in run.stops),
        run.revision,
        run.provider_id,
        run.objective,
    )


def _failures() -> st.SearchStrategy[Script]:
    return st.one_of(
        st.just(TourNoRoute()),
        st.just(TourTimedOut()),
        st.builds(
            TourOptimizerFailed,
            exit_code=st.none() | st.integers(1, 255),
            signal=st.none() | st.integers(1, 31),
        ),
        st.sampled_from([RuntimeError("the solver broke"), SolveAbandonedError("the scenario ended")]),
    )


@st.composite
def plans(draw: st.DrawFn) -> Plan:
    trip = draw(trips())
    visited = [item.id for item in trip.items]
    found = TourFound(order=(trip.start.id, *draw(st.permutations(visited)), trip.end.id))
    return Plan(trip, draw(st.just(found) | _failures()), draw(st.integers(0, 3)))


def _expected_stops(trip: Trip, order: tuple[str, ...]) -> tuple[tuple[str, str, float | None], ...]:
    """Start first and End last, each later stop with the road from where the previous one is left (HC-1, HC-2)."""
    items = {item.id: item for item in (trip.start, trip.end, *trip.items)}
    trail = [items[item_id] for item_id in order]
    first: tuple[str, str, float | None] = (trail[0].id, _kind(trail[0]), None)
    later = tuple(
        (item.id, _kind(item), trip.road_m(left_at(previous), reached_at(item)) / 1000)
        for previous, item in itertools.pairwise(trail)
    )
    return (first, *later)


def _kind(item: CatalogItem) -> str:
    return "track" if isinstance(item, TrackItem) else "poi"


def _expected_row(plan: Plan) -> tuple[Any, ...] | None:
    """The one row the job stores, or `None` when the script raised (D122; a raising job stores nothing)."""
    number = plan.earlier_runs + 1
    stamp = (DEFAULT_STAMP.revision, RecordingRoadMap.provider_id, DEFAULT_STAMP.objective)
    if isinstance(plan.script, Exception):
        return None
    if isinstance(plan.script, TourFound):
        return (number, "ready", None, _expected_stops(plan.trip, plan.script.order), *stamp)
    assert plan.script is not None
    return (number, "failed", plan.script.reason, (), *stamp)


@settings(deadline=None)
@given(plan=plans())
def test_any_solver_outcome_ends_in_one_terminal_state_with_a_run_named_iff_one_was_stored(plan: Plan) -> None:
    planner = _planner(plan.trip, plan.script)
    for number in range(1, plan.earlier_runs + 1):
        planner.planning.seed_run(PROJECT, number)
    before = planner.view()

    job_id = planner.service.request(PROJECT)
    job = planner.wait_until_ended(job_id)

    row = _expected_row(plan)
    delta = {} if row is None else {"plan_runs": gained(row)}
    assert_state_delta(before, planner.view(), UNIVERSE, delta, strict=True)
    if row is None:
        assert (job.state, job.reason, job.message, job.plan_run_id) == ("failed", None, FAILED_MESSAGE, None)
    else:
        assert (job.state, job.reason, job.message) == ("done", row[2], None)
        stored = planner.queries.get(str(job.plan_run_id))
        assert stored is not None, "the job names a run that is not stored"
        assert (stored.project_id, stored.number, stored.status, stored.failure_reason) == (PROJECT, *row[:3])
        assert tuple((stop.item_id, stop.kind, stop.leg_km) for stop in stored.stops) == row[3]
    assert planner.poll(job_id) == job, "a terminal state does not change"
    assert planner.queries.get("no-such-run") is None
    assert planner.solver.budgets == [BUDGET]


@settings(deadline=None)
@given(trip=trips(), stage=st.sampled_from(["queued", "computing_legs", "solving", "finalising"]))
def test_the_request_answers_before_the_job_is_done_and_no_run_is_named_until_stored(trip: Trip, stage: str) -> None:
    pairs = SolverModelBuilder(trip.snapshot).required_pairs()
    assume(stage != "computing_legs" or any(origin != destination for origin, destination in pairs))
    planner = _planner(trip, held_at=stage)
    before = planner.view()

    job_id = planner.service.request(PROJECT)

    planner.wait_until_held()
    job = planner.poll(job_id)
    assert (job.state, job.plan_run_id) == (stage, None)
    assert_state_delta(before, planner.view(), UNIVERSE, {}, strict=True)

    planner.held.release()
    ended = planner.wait_until_ended(job_id)
    assert ended.state == "done"
    assert ended.plan_run_id is not None
    assert planner.solver.threads[0] is not threading.current_thread(), "solve ran on the request's thread"
    assert planner.solver.threads[0].daemon, "a running job would block process exit"


@settings(deadline=None)
@given(trip=trips())
def test_the_project_stays_readable_while_the_optimizer_works(trip: Trip) -> None:
    planner = _planner(trip, held_at="solving")
    before = [run.id for run in planner.queries.list(PROJECT)]

    job_id = planner.service.request(PROJECT)
    planner.wait_until_held()

    assert [run.id for run in planner.queries.list(PROJECT)] == before, "the job holds the writer lock while solving"
    planner.held.release()
    planner.wait_until_ended(job_id)


@settings(deadline=None)
@given(trip=trips(), waited_s=st.floats(0, 2 * KEPT_FOR_S, allow_nan=False), ended=st.booleans())
def test_a_finished_job_is_kept_for_ten_minutes_and_a_running_one_as_long_as_it_runs(
    trip: Trip, waited_s: float, ended: bool
) -> None:
    planner = _planner(trip, held_at=None if ended else "solving")
    job_id = planner.service.request(PROJECT)
    if ended:
        planner.wait_until_ended(job_id)
    else:
        planner.wait_until_held()
    started_at = planner.clock.monotonic()

    planner.clock.advance(waited_s)

    job = planner.registry.get(job_id)
    waited = planner.clock.monotonic() - started_at
    if ended and waited >= KEPT_FOR_S:
        assert job is None, "an expired job is not known any more"
    else:
        assert job is not None, "the job was forgotten too early"
        assert job.elapsed_s == (0.0 if ended else waited), "elapsed time runs until the job ends"
    assert planner.registry.get("no-such-job") is None
    planner.held.release()


@settings(deadline=None)
@given(plan=plans())
def test_a_job_logs_one_finished_event_and_a_stored_run_one_completed_event(plan: Plan) -> None:
    planner = _planner(plan.trip, plan.script)

    job_id = planner.service.request(PROJECT)
    job = planner.wait_until_ended(job_id)

    events = planner.log.events
    finished = [fields for event, fields in events if event == "plan.job.finished"]
    completed = [fields for event, fields in events if event == "plan.run.completed"]
    assert len(finished) == 1
    fields = finished[0]
    assert set(fields) >= KPI_FIELDS
    assert (fields["job_id"], fields["project_id"], fields["terminal_state"], fields["plan_run_id"]) == (
        job_id,
        PROJECT,
        job.state,
        job.plan_run_id,
    )
    assert all(fields[name] is None for name in FIELDS_OF_LATER_SLICES)
    assert fields["elapsed_ms"] == 0
    assert (fields["legs_total"], fields["provider_id"]) == (
        len(_distinct_pairs(plan.trip)),
        RecordingRoadMap.provider_id,
    )
    assert fields["items_included"] == len({plan.trip.start.id, plan.trip.end.id, *(i.id for i in plan.trip.items)})
    if isinstance(plan.script, TourOptimizerFailed):
        assert (fields["exit_code"], fields["signal"]) == (plan.script.exit_code, plan.script.signal)
    if isinstance(plan.script, Exception):
        assert fields["error_class"] == type(plan.script).__name__
        assert completed == []
        return
    assert len(completed) == 1
    assert set(completed[0]) == RUN_FIELDS
    stored = planner.planning.runs[-1]
    assert (completed[0]["plan_run_id"], completed[0]["number"], completed[0]["status"]) == (
        stored.id,
        stored.number,
        stored.status,
    )
    assert completed[0]["failure_reason"] == stored.failure_reason
    assert completed[0]["project_items"] == len(plan.trip.snapshot.items)
    assert (completed[0]["report_items"], completed[0]["invariants"]) == (None, None)


def _distinct_pairs(trip: Trip) -> set[Any]:
    return set(SolverModelBuilder(trip.snapshot).required_pairs())

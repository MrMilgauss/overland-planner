"""The plan job (US-02b, brief section 8, ADR-015, D122): Calculate answers at once; the job ends in one terminal state.

Driving ports: `PlanRequestService`, `PlanJobRegistry` (polling) and `PlanRunQueries` from the planning facade, over the
real `PlanRequestJob` and `LegResolver`. Driven ports: `PlanningUnitOfWork`, `RoutingProvider`, `TourSolver` (scripted),
`Clock` (`FakeClock`, which never moves by itself) and `EventLog`.
Observable universe: `plan_runs` as the database double holds them, `items` and `projects` as planning reads them; for
several projects (`PlanDesk`) `plan_runs`, `jobs` as polled and `refusals_logged`.
Test Budget: 7 behaviors (any solver outcome ends the job in one terminal state with at most one stored run; the request
answers before the job is done and no run is named until stored; finished jobs are kept for 10 minutes and running ones
always; each job logs its events; one active job per project, whatever the presses and endings; one solver slot, freed
by every ending; the active job check keeps its place in the pre-checks and cannot be slipped past) x 2 = 14; 10 used.
"""

from __future__ import annotations

import itertools
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,
)

from overland_planner.application.planning.facade import (
    PlanJobRegistry,
    PlanJobView,
    PlanRefusedError,
    PlanRequestJob,
    PlanRequestService,
    PlanRunQueries,
)
from overland_planner.application.platform.facade import HealthDetail, HealthService
from overland_planner.application.ports.plan_run_repository import NewPlanRun
from overland_planner.application.ports.probe import ProbeOutcome, ProbeResult
from overland_planner.application.ports.tour_solver import (
    TourFound,
    TourNoRoute,
    TourOptimizerFailed,
    TourOutcome,
    TourTimedOut,
)
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder, TourModel
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.predicates import gained
from tests.common.solver_fakes import SolveAbandonedError
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.application.planning.planning_doubles import (
    DEFAULT_STAMP,
    MAX_WAIT_S,
    TERMINAL_STATES,
    Gate,
    InMemoryPlanning,
    RecordingRoadMap,
    job_when_ended,
    known_job,
)
from tests.unit.application.planning.scripted_tour_solver import Script, ScriptedTourSolver
from tests.unit.domain.planning.trips import PROJECT, Trip, left_at, reached_at, trips

UNIVERSE = {"plan_runs", "items", "projects"}
BUDGET = 500
KEPT_FOR_S = 600.0
FAILED_MESSAGE = "The plan could not be calculated - nothing was changed"
KPI_FIELDS = {  # docs/product/kpi-contracts.yaml, plan.job.finished, without those of `_fields_of_the_ending`
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
        return known_job(self.registry, job_id)

    def wait_until_ended(self, job_id: str) -> PlanJobView:
        return job_when_ended(self.registry, job_id)

    def wait_until_held(self) -> None:
        assert self.held.reached.wait(MAX_WAIT_S), "the job never reached the gate"


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
    files = InMemoryFileStore()
    trip.seed_canonical_files(files)
    job = PlanRequestJob(planning.unit_of_work, LegResolver(road_map), solver, BUDGET, clock, log, files)
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
@given(trip=trips(), fatal=st.sampled_from([SystemExit(3), KeyboardInterrupt(), GeneratorExit()]))
def test_whatever_the_work_raises_the_job_ends_failed_and_calculate_is_accepted_again(
    trip: Trip, fatal: BaseException
) -> None:
    planner = _planner(trip, fatal)
    before = planner.view()

    first = planner.service.request(PROJECT)
    job = planner.wait_until_ended(first)

    assert (job.state, job.reason, job.message, job.plan_run_id) == ("failed", None, FAILED_MESSAGE, None)
    finished = planner.log.fields_of("plan.job.finished")
    assert [(fields["job_id"], fields["terminal_state"], fields["error_class"]) for fields in finished] == [
        (first, "failed", type(fatal).__name__)
    ]
    assert_state_delta(before, planner.view(), UNIVERSE, {}, strict=True)

    second = planner.service.request(PROJECT)  # the project is not held in 409, and the ending freed the solver slot
    assert second != first
    assert planner.wait_until_ended(second).state == "failed"
    assert planner.solver.budgets == [BUDGET, BUDGET]


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
    assert set(fields) == KPI_FIELDS | _fields_of_the_ending(plan.script)
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
    assert completed[0]["report_items"] is None
    assert completed[0]["invariants"] == ("ok" if stored.status == "ready" else None)


def _fields_of_the_ending(script: Script) -> set[str]:
    """The fields of the contract that are logged only on the endings they describe."""
    if isinstance(script, Exception):
        return {"error_class"}
    if isinstance(script, TourOptimizerFailed):
        return {"reason", "exit_code", "signal"}
    return set() if isinstance(script, TourFound) else {"reason"}


def _distinct_pairs(trip: Trip) -> set[Any]:
    return set(SolverModelBuilder(trip.snapshot).required_pairs())


# ------------------------------------------------------------------------ one plan at a time (ADR-015, D133)
PROJECTS = ("project-1", "project-2", "project-3")  # three: D133 does not refuse the third, it waits for the slot
DESK_UNIVERSE = {"plan_runs", "jobs", "refusals_logged"}
JOB_ACTIVE = ("job_active", 409, "A plan is already being calculated for this project")
WORKING_STATES = {"solving", "waiting_for_optimizer"}


class SolverOnCue:
    """Each solve waits for its cue, then answers like `ScriptedTourSolver` with the cued script; no child process."""

    def __init__(self) -> None:
        self.solving = 0
        self.most_at_once = 0
        self.solves = 0
        self._cues: queue.SimpleQueue[Script] = queue.SimpleQueue()
        self._lock = threading.Lock()

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def cue(self, script: Script) -> None:
        self._cues.put(script)

    def solve(self, model: TourModel, budget: int) -> TourOutcome:
        with self._lock:
            self.solves += 1
            self.solving += 1
            self.most_at_once = max(self.most_at_once, self.solving)
        try:
            return ScriptedTourSolver(self._cues.get(timeout=MAX_WAIT_S)).solve(model, budget)
        finally:
            with self._lock:
                self.solving -= 1


def _until(reached: Callable[[], bool], what: str) -> None:
    """Waits for a job's thread by yielding to it, with no fixed pause; the deadline only stops a hung test."""
    deadline = time.monotonic() + MAX_WAIT_S
    while not reached():
        assert time.monotonic() < deadline, f"never happened: {what}"
        time.sleep(0)


def _optimizer(outcome: ProbeOutcome = "ok") -> HealthService:
    return HealthService({"tour_solver": ProbeResult(outcome)})


@dataclass
class PlanDesk:
    """The real services over the doubles, with several projects open; `accepted` is every press that got a job."""

    planning: InMemoryPlanning
    solver: SolverOnCue
    log: RecordingEventLog
    registry: PlanJobRegistry
    service: PlanRequestService
    queries: PlanRunQueries
    accepted: list[tuple[str, str]] = field(default_factory=list)

    def service_with(self, health: HealthService) -> PlanRequestService:
        return PlanRequestService(self.planning.unit_of_work, health, self.log, self.registry)

    def press(self, project_id: str, service: PlanRequestService | None = None) -> str | PlanRefusedError:
        try:
            job_id = (service or self.service).request(project_id)
        except PlanRefusedError as refused:
            return refused
        self.accepted.append((job_id, project_id))
        return job_id

    def poll(self, job_id: str) -> PlanJobView:
        return known_job(self.registry, job_id)

    def state(self, job_id: str) -> str:
        return self.poll(job_id).state

    def jobs_in(self, *states: str) -> list[str]:
        return [job_id for job_id, _ in self.accepted if self.state(job_id) in states]

    def still_working(self) -> list[str]:
        return [job_id for job_id, _ in self.accepted if self.state(job_id) not in TERMINAL_STATES]

    def until_state(self, job_id: str, state: str) -> None:
        _until(lambda: self.state(job_id) == state, f"job in {state}, it is {self.poll(job_id)}")

    def until_ended(self, job_id: str) -> PlanJobView:
        _until(lambda: self.state(job_id) in TERMINAL_STATES, f"job ended, it is {self.poll(job_id)}")
        return self.poll(job_id)

    def until_settled(self) -> None:
        """Every working job either is the one solve under way or waits for it."""

        def settled() -> bool:
            assert self.solver.most_at_once <= 1, "two solver children ran at once"
            working = self.still_working()
            solving = self.jobs_in("solving")
            return (
                all(self.state(job_id) in WORKING_STATES for job_id in working)
                and len(solving) == (1 if working else 0)
                and self.solver.solving == len(solving)
            )

        _until(settled, f"the jobs settled, they are {[self.poll(job_id) for job_id, _ in self.accepted]}")

    def view(self) -> dict[str, Any]:
        refusals = self.log.fields_of("plan.job.refused")
        return {
            "plan_runs": tuple((r.project_id, r.number, r.status, r.failure_reason) for r in self.planning.runs),
            "jobs": tuple(
                (job_id, project_id, self.state(job_id), self.poll(job_id).plan_run_id)
                for job_id, project_id in self.accepted
            ),
            "refusals_logged": tuple((f["project_id"], f["http_status"], f["reason"]) for f in refusals),
        }


def _plan_desk(trip: Trip, health: HealthService | None = None) -> PlanDesk:
    planning = InMemoryPlanning()
    for project_id in PROJECTS:
        planning.add_project(project_id, trip.snapshot)
    solver = SolverOnCue()
    clock = FakeClock()
    log = RecordingEventLog()
    files = InMemoryFileStore()
    trip.seed_canonical_files(files)
    road_map = RecordingRoadMap(trip.leg_m)
    job = PlanRequestJob(planning.unit_of_work, LegResolver(road_map), solver, BUDGET, clock, log, files)
    registry = PlanJobRegistry(clock, job, log)
    service = PlanRequestService(planning.unit_of_work, health or _optimizer(), log, registry)
    return PlanDesk(planning, solver, log, registry, service, PlanRunQueries(planning.unit_of_work))


def _endings() -> st.SearchStrategy[Script]:
    return st.none() | _failures()


def _ending_of(script: Script) -> tuple[str, str | None, bool]:
    """Terminal state, failure reason of the run, and whether a run is stored (D122; a raising job stores nothing)."""
    if isinstance(script, Exception):
        return "failed", None, False
    if script is None or isinstance(script, TourFound):
        return "done", None, True
    return "done", script.reason, True


def _refusal_of(refused: PlanRefusedError) -> tuple[str, int, str]:
    return refused.reason, refused.http_status, str(refused)


class OnePlanAtATime(RuleBasedStateMachine):
    """Any sequence of presses and solver answers over several projects, with the model of who is working."""

    desk: PlanDesk
    working_project_of: dict[str, str]

    @initialize(trip=trips())
    def open_the_projects(self, trip: Trip) -> None:
        self.desk = _plan_desk(trip)
        self.working_project_of = {}

    @rule(project_id=st.sampled_from(PROJECTS))
    def press_calculate(self, project_id: str) -> None:
        before = self.desk.view()
        answer = self.desk.press(project_id)
        if isinstance(answer, PlanRefusedError):
            assert project_id in self.working_project_of.values(), f"refused with nothing active: {answer}"
            assert _refusal_of(answer) == JOB_ACTIVE
            logged = (*before["refusals_logged"], (project_id, JOB_ACTIVE[1], JOB_ACTIVE[0]))
            assert_state_delta(
                before, self.desk.view(), DESK_UNIVERSE, {"refusals_logged": set_to(logged)}, strict=True
            )
            return
        assert project_id not in self.working_project_of.values(), "a second job started for the project"
        expected_state = "waiting_for_optimizer" if self.working_project_of else "solving"
        self.working_project_of[answer] = project_id
        self.desk.until_settled()
        jobs = (*before["jobs"], (answer, project_id, expected_state, None))
        assert_state_delta(before, self.desk.view(), DESK_UNIVERSE, {"jobs": set_to(jobs)}, strict=True)

    @precondition(lambda self: bool(self.working_project_of))
    @rule(script=_endings())
    def the_solver_answers(self, script: Script) -> None:
        before = self.desk.view()
        (job_id,) = self.desk.jobs_in("solving")
        project_id = self.working_project_of[job_id]
        self.desk.solver.cue(script)

        ended = self.desk.until_ended(job_id)
        del self.working_project_of[job_id]
        self.desk.until_settled()

        state, reason, stored = _ending_of(script)
        assert (ended.state, ended.reason) == (state, reason)
        assert (ended.plan_run_id is not None) == stored
        delta: dict[str, Any] = {"jobs": _one_ended_and_the_next_solving(job_id, state)}
        if stored:
            number = sum(run.project_id == project_id for run in self.desk.planning.runs)
            status = "ready" if reason is None else "failed"
            delta["plan_runs"] = gained((project_id, number, status, reason))
            assert self.desk.planning.runs[-1].id == ended.plan_run_id
        assert_state_delta(before, self.desk.view(), DESK_UNIVERSE, delta, strict=True)

    @invariant()
    def one_job_per_project_and_one_in_the_solver(self) -> None:
        working = self.desk.still_working()
        assert set(working) == set(self.working_project_of), "the model and the polls disagree on who is working"
        projects = list(self.working_project_of.values())
        assert len(projects) == len(set(projects)), f"a project has two active jobs: {projects}"
        assert len(self.desk.jobs_in("solving")) == (1 if working else 0)
        assert self.desk.solver.most_at_once <= 1, "two solver children ran at once"
        assert all(self.desk.poll(job_id).plan_run_id is None for job_id in working), "a working job names a run"

    def teardown(self) -> None:
        if not hasattr(self, "desk"):
            return
        for job_id in self.desk.still_working():
            self.desk.solver.cue(None)
            self.desk.until_ended(job_id)
        finished = [fields["job_id"] for fields in self.desk.log.fields_of("plan.job.finished")]
        assert sorted(finished) == sorted(job_id for job_id, _ in self.desk.accepted), "a press without one ending"


def _one_ended_and_the_next_solving(ended_job_id: str, terminal_state: str) -> Callable[[Any, Any], bool]:
    def predicate(old: tuple[tuple[Any, ...], ...], new: tuple[tuple[Any, ...], ...]) -> bool:
        before = {row[0]: row for row in old}
        if set(before) != {row[0] for row in new}:
            return False
        return all(_moved_as_expected(before[row[0]], row, ended_job_id, terminal_state) for row in new)

    return predicate


def _moved_as_expected(old: tuple[Any, ...], new: tuple[Any, ...], ended_job_id: str, terminal_state: str) -> bool:
    if new[0] == ended_job_id:
        return new[1] == old[1] and new[2] == terminal_state
    return new == old or (new == (*old[:2], "solving", None) and old[2] == "waiting_for_optimizer")


def test_any_presses_and_endings_keep_one_job_per_project_and_one_in_the_solver() -> None:
    run_state_machine_as_test(OnePlanAtATime, settings=settings(max_examples=25, stateful_step_count=12, deadline=None))


@settings(deadline=None)
@given(trip=trips(), ending=_endings())
def test_another_project_waits_for_the_solver_slot(trip: Trip, ending: Script) -> None:
    desk = _plan_desk(trip)
    first = desk.press("project-1")
    assert isinstance(first, str)
    desk.until_settled()
    before = desk.view()

    second = desk.press("project-2")
    assert isinstance(second, str)
    desk.until_state(second, "waiting_for_optimizer")

    jobs = (*before["jobs"], (second, "project-2", "waiting_for_optimizer", None))
    assert_state_delta(before, desk.view(), DESK_UNIVERSE, {"jobs": set_to(jobs)}, strict=True)
    assert desk.solver.solves == 1, "the waiting job reached the solver"
    assert desk.queries.list("project-2") == [], "the waiting job has a run, or keeps the project unreadable"

    desk.solver.cue(ending)
    ended = desk.until_ended(first)  # the waiting job must not stop the other from finishing, whatever its ending

    assert ended.state == _ending_of(ending)[0]
    desk.until_state(second, "solving")  # and every ending frees the slot
    desk.solver.cue(None)
    assert desk.until_ended(second).state == "done"
    assert [run.status for run in desk.queries.list("project-2")] == ["ready"]
    assert desk.solver.most_at_once == 1


@settings(deadline=None)
@given(trip=trips(), anchors_set=st.booleans(), optimizer=st.sampled_from(["ok", "degraded-unhealthy"]))
def test_the_active_job_check_comes_after_the_anchors_and_before_the_optimizer(
    trip: Trip, anchors_set: bool, optimizer: ProbeOutcome
) -> None:
    desk = _plan_desk(trip)
    first = desk.press("project-1")
    assert isinstance(first, str)
    desk.until_settled()
    if not anchors_set:
        desk.planning.snapshots["project-1"] = ProjectSnapshot()
    before = desk.view()

    refused = desk.press("project-1", desk.service_with(_optimizer(optimizer)))

    assert isinstance(refused, PlanRefusedError), "a press started a second job"
    expected = JOB_ACTIVE if anchors_set else ("missing_anchor", 422, "Set the Start before calculating")
    assert _refusal_of(refused) == expected
    logged = (("project-1", expected[1], expected[0]),)
    assert_state_delta(before, desk.view(), DESK_UNIVERSE, {"refusals_logged": set_to(logged)}, strict=True)
    desk.solver.cue(None)
    desk.until_ended(first)


class _APressSlipsIn(HealthService):
    """A second fast press lands between the first press's pre-checks and the start of its job."""

    def __init__(self) -> None:
        super().__init__({"tour_solver": ProbeResult("ok")})
        self.press: Callable[[], object] | None = None

    def detail(self) -> HealthDetail:
        press, self.press = self.press, None
        if press is not None:
            press()
        return super().detail()


@settings(deadline=None)
@given(trip=trips())
def test_two_fast_presses_start_one_job(trip: Trip) -> None:
    health = _APressSlipsIn()
    desk = _plan_desk(trip, health)
    health.press = lambda: desk.press("project-1")
    before = desk.view()

    refused = desk.press("project-1")

    assert isinstance(refused, PlanRefusedError), f"both presses started a job: {desk.accepted}"
    assert _refusal_of(refused) == JOB_ACTIVE
    desk.until_settled()
    ((job_id, _),) = desk.accepted
    jobs = ((job_id, "project-1", "solving", None),)
    logged = (("project-1", JOB_ACTIVE[1], JOB_ACTIVE[0]),)
    assert_state_delta(
        before, desk.view(), DESK_UNIVERSE, {"jobs": set_to(jobs), "refusals_logged": set_to(logged)}, strict=True
    )
    desk.solver.cue(None)
    desk.until_ended(job_id)
    assert desk.solver.solves == 1

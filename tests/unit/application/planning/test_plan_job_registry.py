"""The plan job (US-02b, brief section 8, ADR-015, D122): Calculate answers at once; the job ends in one terminal state.

Driving ports: `PlanRequestService`, `PlanJobRegistry` (polling) and `PlanRunQueries` from the planning facade, over the
real `PlanRequestJob` and `LegResolver`. Driven ports: `PlanningUnitOfWork`, `RoutingProvider`, `TourSolver` (scripted),
`Clock` (`FakeClock`, which never moves by itself) and `EventLog`.
Observable universe: `plan_runs` as the database double holds them, `items` and `projects` as planning reads them, and
`plan_job_log` as the `PlanJobLog` double holds it (ADR-015 DV-2); for several projects (`PlanDesk`) `plan_runs`, `jobs`
as polled and `refusals_logged`; for Stop (`StopDesk`) the project's `plan_runs` with their flags, its `plan_job_log`
rows and the `plan.job.stopped` events (`stopped_logged`).
Test Budget: 8 behaviors (any solver outcome ends the job in one terminal state with at most one stored run; the request
answers before the job is done and no run is named until stored; finished jobs are kept for 10 minutes and running ones
always; each job logs its events; one active job per project, whatever the presses and endings; one solver slot, freed
by every ending; the active job check keeps its place in the pre-checks and cannot be slipped past; Calculate reports
the `ignore_memo` it was given and refuses alike with or without it; every ending writes one `plan_job_log` row with
the values of its line, a refusal none, and a failing write changes nothing else; a Stop ends the job as ADR-015's
state table names and answers the current payload; a job waiting for the optimizer gives up at the feasibility limit;
a Stop or the feasibility limit during the road look-up ends the job at once, with no run and the legs found kept)
x 2 = 24; 18 used.
"""

from __future__ import annotations

import itertools
import queue
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import pytest
from hypothesis import assume, example, given, settings
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
from overland_planner.application.ports.plan_job_log import PLAN_JOB_LOG_FIELDS
from overland_planner.application.ports.plan_run_repository import NewPlanRun
from overland_planner.application.ports.probe import ProbeOutcome, ProbeResult
from overland_planner.application.ports.tour_solver import (
    Incumbent,
    IncumbentObserver,
    SolveLimits,
    TourFound,
    TourNoRoute,
    TourOptimizerFailed,
    TourOutcome,
    TourSolver,
    TourTimedOut,
    ignore_incumbents,
)
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
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
    InMemoryPlanJobLog,
    InMemoryPlanning,
    RecordingRoadMap,
    job_when_ended,
    known_job,
)
from tests.unit.application.planning.scripted_tour_solver import Script, ScriptedTourSolver
from tests.unit.domain.planning.trips import POINT_PAIRS, POINTS, PROJECT, Trip, left_at, leg_table, reached_at, trips

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
    "stage_ms",
    "job_id",
    "project_id",
    "terminal_state",
    "plan_run_id",
    "items_included",
    "legs_total",
    "legs_new",  # 06-09 fills these two (the leg cache)
    "legs_cached",
    "provider_id",
    "elapsed_ms",
    "memo_hit",
    "ignore_memo",
    "incumbents",  # 06-06 fills these three (test_plan_request_job_outcomes.py)
    "reproducible",
    "not_fully_optimised_reason",
}
RUN_FIELDS = {
    "plan_run_id",
    "number",
    "status",
    "failure_reason",
    "report_items",
    "project_items",
    "invariants",
    "memo_hit",
    "ignore_memo",
}


@dataclass(frozen=True)
class Plan:
    trip: Trip
    script: Script
    earlier_runs: int


@dataclass
class Planner:
    """The real plan job and its services over the doubles of the driven ports. `held` is the gate the job stops at."""

    planning: InMemoryPlanning
    solver: Any
    clock: FakeClock
    log: RecordingEventLog
    registry: PlanJobRegistry
    service: PlanRequestService
    queries: PlanRunQueries
    held: Gate
    job_log: InMemoryPlanJobLog

    def view(self) -> dict[str, Any]:
        snapshot = self.planning.snapshots[PROJECT]
        stamp = self.planning.stamps[PROJECT]
        return {
            "plan_runs": tuple(_row(run) for run in self.planning.runs if run.project_id == PROJECT),
            "items": tuple(item.id for item in snapshot.items),
            "projects": (PROJECT, stamp, snapshot.start_item_id, snapshot.end_item_id),
        }

    def logged_view(self) -> dict[str, Any]:
        rows = (entry.columns() for entry in self.job_log.rows)
        return {
            **self.view(),
            "plan_job_log": tuple(tuple(row[name] for name in LOG_ROW_KEY) for row in rows),
            "log_failures_warned": tuple(
                (fields["job_id"], fields["project_id"], fields["error_class"])
                for fields in self.log.fields_of("plan.job.log_failed")
            ),
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


def _planner(
    trip: Trip, script: Script = None, *, held_at: str | None = None, scripts: list[Script] | None = None
) -> Planner:
    """`scripts`: one script per solve, in turn, instead of `script` for every solve."""
    gates = {
        "queued": _HeldBehindThePreCheck() if held_at == "queued" else Gate(),
        "computing_legs": Gate(held=held_at == "computing_legs"),
        "solving": Gate(held=held_at == "solving"),
        "finalising": Gate(held=held_at == "finalising"),
    }
    planning = InMemoryPlanning(reading=gates["queued"], storing=gates["finalising"])
    planning.add_project(PROJECT, trip.snapshot)
    road_map = RecordingRoadMap(trip.leg_m, gate=gates["computing_legs"])
    solver: TourSolver = (
        ScriptedTourSolver(script, gate=gates["solving"])
        if scripts is None
        else _ScriptsInTurn(scripts, gates["solving"])
    )
    clock = FakeClock()
    log = RecordingEventLog()
    files = InMemoryFileStore()
    trip.seed_canonical_files(files)
    job = PlanRequestJob(planning.unit_of_work, LegResolver(road_map), solver, BUDGET, clock, log, files)
    job_log = InMemoryPlanJobLog(planning)
    registry = PlanJobRegistry(clock, job, log, job_log=job_log)
    health = HealthService({"tour_solver": ProbeResult("ok")})
    service = PlanRequestService(planning.unit_of_work, health, log, registry)
    queries = PlanRunQueries(planning.unit_of_work)
    held = gates.get(held_at or "", Gate())
    return Planner(planning, solver, clock, log, registry, service, queries, held, job_log)


class _ScriptsInTurn:
    """Answers each solve like `ScriptedTourSolver` with the next of its scripts."""

    identity = "scripts-in-turn"

    def __init__(self, scripts: list[Script], gate: Gate) -> None:
        self._scripts = list(scripts)
        self._gate = gate

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def solve(
        self,
        model: TourModel,
        budget: int,
        _on_incumbent: IncumbentObserver = ignore_incumbents,
        *,
        deadlines: object = None,  # the job's deadlines (06-07); this double ends as scripted, whatever they are
        stop: object = None,  # the job's stop signal (06-08); nobody stops these solves
    ) -> TourOutcome:
        self._gate.passing()
        script = self._scripts.pop(0)
        if isinstance(script, BaseException):
            raise script
        return script if script is not None else TourFound(order=model.node_item_ids)


def _failed_job_message(reason: str | None, number: int) -> str | None:
    """What an ended job says of its Failed run, as Marco reads it (D151); only a timeout has words yet."""
    return f"No valid route found within the time limit - plan run #{number} failed" if reason == "timeout" else None


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


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
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
        assert (job.state, job.reason, job.message) == ("done", row[2], _failed_job_message(row[2], row[0]))
        stored = planner.queries.get(str(job.plan_run_id))
        assert stored is not None, "the job names a run that is not stored"
        assert (stored.project_id, stored.number, stored.status, stored.failure_reason) == (PROJECT, *row[:3])
        assert tuple((stop.item_id, stop.kind, stop.leg_km) for stop in stored.stops) == row[3]
    assert planner.poll(job_id) == job, "a terminal state does not change"
    assert planner.queries.get("no-such-run") is None
    assert planner.solver.budgets == [BUDGET]


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
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


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
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


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
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


def _round_trip_from_home() -> Trip:
    """The smallest trip: Start and End the same place, nothing to visit."""
    home = PoiItem(id="start", project_id=PROJECT, name="Casa Marco", location=POINTS[0])
    leg_m = {pair: number for number, pair in enumerate(POINT_PAIRS, start=1)}
    return Trip(ProjectSnapshot(home.id, home.id, (home,)), leg_table(leg_m), leg_m, home, home, ())


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@settings(deadline=None)
@given(
    trip=trips(),
    waited_s=st.one_of(st.just(KEPT_FOR_S), st.floats(0, 2 * KEPT_FOR_S, allow_nan=False)),  # ten minutes is gone
    ended=st.booleans(),
)
@example(trip=_round_trip_from_home(), waited_s=KEPT_FOR_S, ended=True)  # exactly ten minutes: gone, on every run
@example(trip=_round_trip_from_home(), waited_s=KEPT_FOR_S, ended=False)  # still running: kept
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
        assert (job.id, job.project_id) == (job_id, PROJECT), "the poll names its job and project"
        assert job.elapsed_s == (0.0 if ended else waited), "elapsed time runs until the job ends"
    assert planner.registry.get("no-such-job") is None
    planner.held.release()


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
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
    assert (fields["memo_hit"], fields["ignore_memo"]) == (False, False)  # a plain Calculate of a job without a memo
    assert fields["elapsed_ms"] == 0
    assert (fields["legs_total"], fields["provider_id"]) == (
        len(_distinct_pairs(plan.trip)),
        RecordingRoadMap.provider_id,
    )
    roads = {pair for pair in _distinct_pairs(plan.trip) if pair[0] != pair[1]}
    assert (fields["legs_new"], fields["legs_cached"]) == (len(roads), len(_distinct_pairs(plan.trip)) - len(roads))
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
    assert (completed[0]["memo_hit"], completed[0]["ignore_memo"]) == (False, False)


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@settings(deadline=None)
@given(
    trip=trips(),
    raised=st.sampled_from([RuntimeError("the solver broke"), SystemExit(3)]),
    stored=st.sampled_from([None, TourNoRoute(), TourTimedOut(), TourOptimizerFailed(exit_code=1, signal=None)]),
)
def test_a_failed_job_logs_its_end_at_warning_and_a_done_job_at_info(
    trip: Trip, raised: BaseException, stored: Script
) -> None:
    for script, state, level in ((raised, "failed", "warning"), (stored, "done", "info")):
        planner = _planner(trip, script)

        job = planner.wait_until_ended(planner.service.request(PROJECT))

        assert job.state == state
        assert planner.log.levels_of("plan.job.finished") == [level]


@settings(deadline=None)
@given(trip=trips(), exit_code=st.integers(32, 255), signal=st.integers(1, 31))
def test_an_optimizer_failure_logs_both_the_exit_code_and_the_signal_of_the_child(
    trip: Trip, exit_code: int, signal: int
) -> None:
    planner = _planner(trip, TourOptimizerFailed(exit_code=exit_code, signal=signal))

    planner.wait_until_ended(planner.service.request(PROJECT))

    (fields,) = planner.log.fields_of("plan.job.finished")
    assert (fields["reason"], fields["exit_code"], fields["signal"]) == ("optimizer_failed", exit_code, signal)


# ------------------------------------------------------------------------ the job log (ADR-015 DV-2, D93)
LOG_UNIVERSE = UNIVERSE | {"plan_job_log", "log_failures_warned"}
LOG_ROW_KEY = ("job_id", "project_id", "terminal_state", "plan_run_id", "reason", "error_class")
DISK_FULL = OSError(28, "No space left on device")


@dataclass(frozen=True)
class Press:
    """A Calculate press: one that ends (`script`, and whether its log row cannot be written) or one refused."""

    kind: Literal["ending", "optimizer_unavailable", "no_anchors"]
    script: Script = None
    write_fails: bool = False


def _presses() -> st.SearchStrategy[list[Press]]:
    ending = st.builds(
        Press,
        kind=st.just("ending"),
        script=st.none() | _failures(),
        write_fails=st.booleans(),
    )
    refused = st.sampled_from([Press("optimizer_unavailable"), Press("no_anchors")])
    return st.lists(ending | refused, min_size=1, max_size=5)


def _log_row(job_id: str, script: Script, job: PlanJobView) -> tuple[Any, ...]:
    state, reason, _ = _ending_of(script)
    error_class = type(script).__name__ if isinstance(script, BaseException) else None
    return (job_id, PROJECT, state, job.plan_run_id, reason, error_class)


def _refuse(planner: Planner, press: Press) -> PlanRefusedError:
    optimizer = _optimizer("degraded-unhealthy" if press.kind == "optimizer_unavailable" else "ok")
    snapshot = planner.planning.snapshots[PROJECT]
    if press.kind == "no_anchors":
        planner.planning.snapshots[PROJECT] = ProjectSnapshot()
    try:
        PlanRequestService(planner.planning.unit_of_work, optimizer, planner.log, planner.registry).request(PROJECT)
    except PlanRefusedError as refused:
        return refused
    finally:
        planner.planning.snapshots[PROJECT] = snapshot
    raise AssertionError(f"the press was not refused: {press}")


@settings(deadline=None, max_examples=40)
@given(trip=trips(), contended=st.booleans(), presses=_presses())
def test_every_ending_writes_one_log_row_a_refusal_none_and_a_failing_write_changes_nothing_else(
    trip: Trip, contended: bool, presses: list[Press]
) -> None:
    endings = [press for press in presses if press.kind == "ending"]
    first = Press("ending", None, write_fails=False)
    planner = _planner(
        trip,
        held_at="solving" if contended else None,
        scripts=[press.script for press in ([first] if contended else []) + endings],
    )
    before = planner.logged_view()
    rows: list[tuple[Any, ...]] = []
    runs: list[tuple[Any, ...]] = []
    warned: list[tuple[Any, ...]] = []

    def end(job_id: str, press: Press) -> None:
        job = planner.wait_until_ended(job_id)
        state, reason, stored = _ending_of(press.script)
        message = _failed_job_message(reason, len(runs) + 1) if stored else FAILED_MESSAGE
        assert (job.state, job.reason, job.message) == (state, reason, message)
        assert (job.plan_run_id is not None) == stored, f"a run is named iff one is stored: {job}"
        if stored:
            runs.append((len(runs) + 1, "ready" if reason is None else "failed", reason))
        (warned if press.write_fails else rows).append(_log_row(job_id, press.script, job))
        assert planner.poll(job_id) == job, "the write does not change the ending"

    if contended:
        held_job = planner.service.request(PROJECT)
        planner.wait_until_held()
        with_one_active = PlanRequestService(planner.planning.unit_of_work, _optimizer(), planner.log, planner.registry)
        try:
            with_one_active.request(PROJECT)
            raise AssertionError("a second job started while one was active")
        except PlanRefusedError as refused:
            assert _refusal_of(refused) == JOB_ACTIVE
        planner.held.release()
        end(held_job, first)
    for press in presses:
        if press.kind != "ending":
            assert _refuse(planner, press).http_status == (503 if press.kind == "optimizer_unavailable" else 422)
            continue
        planner.job_log.failing = DISK_FULL if press.write_fails else None
        end(planner.service.request(PROJECT), press)

    after = planner.logged_view()
    assert tuple(row[:3] for row in after["plan_runs"]) == tuple(runs), "the runs are what they would have been"
    assert_state_delta(
        before,
        after,
        LOG_UNIVERSE,
        {
            "plan_runs": gained(*after["plan_runs"]) if runs else set_to(()),
            "plan_job_log": gained(*rows) if rows else set_to(()),
            "log_failures_warned": gained(*((row[0], PROJECT, "OSError") for row in warned)) if warned else set_to(()),
        },
        strict=True,
    )


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@settings(deadline=None)
@given(plan=plans(), took_s=st.integers(0, 3_600_000).map(lambda ms: ms / 1000))
def test_a_job_row_holds_the_values_of_its_finished_line_with_its_start_and_end(plan: Plan, took_s: float) -> None:
    planner = _planner(plan.trip, plan.script, held_at="solving")
    started_at = planner.clock.now()

    job_id = planner.service.request(PROJECT)
    planner.wait_until_held()
    planner.clock.advance(took_s)
    planner.held.release()
    planner.wait_until_ended(job_id)

    (line,) = planner.log.fields_of("plan.job.finished")
    (entry,) = planner.job_log.rows
    row = entry.columns()
    assert set(row) == {*PLAN_JOB_LOG_FIELDS, "started_at", "ended_at"}
    assert {name: row[name] for name in PLAN_JOB_LOG_FIELDS if name in line} == {
        name: line[name] for name in PLAN_JOB_LOG_FIELDS if name in line
    }
    assert all(row[name] is None for name in PLAN_JOB_LOG_FIELDS if name not in line), "absent from the line: null"
    assert (row["job_id"], row["started_at"], row["ended_at"]) == (job_id, started_at, planner.clock.now())
    assert row["elapsed_ms"] == round(took_s * 1000)


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

    identity = "solver-on-cue"

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

    def solve(
        self,
        model: TourModel,
        budget: int,
        _on_incumbent: IncumbentObserver = ignore_incumbents,
        *,
        deadlines: object = None,  # the job's deadlines (06-07); this double ends as scripted, whatever they are
        stop: object = None,  # the job's stop signal (06-08); nobody stops these solves
    ) -> TourOutcome:
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
    clock: FakeClock
    log: RecordingEventLog
    registry: PlanJobRegistry
    service: PlanRequestService
    queries: PlanRunQueries
    accepted: list[tuple[str, str]] = field(default_factory=list)

    def service_with(self, health: HealthService) -> PlanRequestService:
        return PlanRequestService(self.planning.unit_of_work, health, self.log, self.registry)

    def press(
        self, project_id: str, service: PlanRequestService | None = None, *, ignore_memo: bool = False
    ) -> str | PlanRefusedError:
        try:
            job_id = (service or self.service).request(project_id, ignore_memo=ignore_memo)
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
    return PlanDesk(planning, solver, clock, log, registry, service, PlanRunQueries(planning.unit_of_work))


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
        # One cue per working job, all up front: the slot names no order (D133), so a later-pressed job may solve
        # first, and a cue per job in press order would leave the earlier one waiting for a cue nobody sends.
        working = self.desk.still_working()
        for _ in working:
            self.desk.solver.cue(None)
        for job_id in working:
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


@pytest.mark.heavy_property  # over 5 s at profile ci on the Mac, about 2.5x that on a runner: slow-properties job
def test_any_presses_and_endings_keep_one_job_per_project_and_one_in_the_solver() -> None:
    run_state_machine_as_test(OnePlanAtATime, settings=settings(max_examples=25, stateful_step_count=12, deadline=None))


@pytest.mark.heavy_property  # over 5 s at profile ci on the Mac, about 2.5x that on a runner: slow-properties job
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


@pytest.mark.heavy_property  # over 5 s at profile ci on the Mac, about 2.5x that on a runner: slow-properties job
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


@pytest.mark.heavy_property  # over 5 s at profile ci on the Mac, about 2.5x that on a runner: slow-properties job
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


# --------------------------------------------------------------- ignore_memo on Calculate (ADR-015 line 21, D74, D218)
FLAG_UNIVERSE = {"plan_runs", "jobs", "refusals_logged"}
MISSING_START = ("missing_anchor", 422, "Set the Start before calculating")
OPTIMIZER_UNAVAILABLE = ("optimizer_unavailable", 503, "Optimizer unavailable - nothing was changed")
REFUSED_PROJECTS = ("project-1", "project-2", "project-3")  # busy, without anchors, with the optimizer down
KEPT_UNDER_S = 60.0  # each wait stays short, so no finished job of the sequence expires (KEPT_FOR_S) while polled


@dataclass(frozen=True)
class FlaggedPress:
    """One accepted Calculate: the flag it sends, how its solve ends, and how long the job runs by the clock."""

    ignore_memo: bool
    ending: Script
    waited_ms: int


@st.composite
def flagged_presses(draw: st.DrawFn) -> list[FlaggedPress]:
    """A sequence holding both flag values, so every rule runs on every example (D212)."""
    flags = [*draw(st.permutations([False, True])), *draw(st.lists(st.booleans(), max_size=2))]
    waited_ms = st.integers(1, int(KEPT_UNDER_S * 1000))
    return [FlaggedPress(flag, draw(_endings()), draw(waited_ms)) for flag in flags]


def _flag_view(desk: PlanDesk) -> dict[str, Any]:
    """The desk's universe, each job also with the `ignore_memo` and `memo_hit` its poll shows."""
    view = desk.view()
    polls = {job_id: desk.poll(job_id) for job_id, _ in desk.accepted}
    view["jobs"] = tuple((*row, polls[row[0]].ignore_memo, polls[row[0]].memo_hit) for row in view["jobs"])
    return view


def _refusals_alike(desk: PlanDesk, unavailable: PlanRequestService) -> dict[bool, list[object]]:
    """Each pre-check refuses a press, once with and once without the flag."""
    answers: dict[bool, list[object]] = {}
    for flag in (False, True):
        presses = [
            desk.press("project-1", ignore_memo=flag),
            desk.press("project-2", ignore_memo=flag),
            desk.press("project-3", unavailable, ignore_memo=flag),
        ]
        answers[flag] = [_refusal_of(answer) if isinstance(answer, PlanRefusedError) else answer for answer in presses]
    return answers


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@settings(deadline=None, max_examples=25)
@given(trip=trips(), presses=flagged_presses())
def test_calculate_reports_the_ignore_memo_it_was_given_and_refuses_alike_with_or_without_it(
    trip: Trip, presses: list[FlaggedPress]
) -> None:
    desk = _plan_desk(trip)
    desk.planning.snapshots["project-2"] = ProjectSnapshot()
    unavailable = desk.service_with(_optimizer("degraded-unhealthy"))
    refusals = tuple(
        (project_id, status, reason)
        for project_id, (reason, status, _) in zip(
            REFUSED_PROJECTS, (JOB_ACTIVE, MISSING_START, OPTIMIZER_UNAVAILABLE), strict=True
        )
    )
    for press in presses:
        before = _flag_view(desk)
        job_id = desk.press("project-1", ignore_memo=press.ignore_memo)
        assert isinstance(job_id, str), f"a Calculate with ignore_memo={press.ignore_memo} was refused: {job_id}"
        desk.until_settled()

        answers = _refusals_alike(desk, unavailable)

        assert answers[False] == answers[True] == [JOB_ACTIVE, MISSING_START, OPTIMIZER_UNAVAILABLE]
        accepted = (job_id, "project-1", "solving", None, press.ignore_memo, False)
        expected = {
            "jobs": set_to((*before["jobs"], accepted)),
            "refusals_logged": set_to((*before["refusals_logged"], *refusals, *refusals)),
        }
        assert_state_delta(before, _flag_view(desk), FLAG_UNIVERSE, expected, strict=True)

        before = _flag_view(desk)
        desk.clock.advance(press.waited_ms / 1000)
        desk.solver.cue(press.ending)
        ended = desk.until_ended(job_id)

        state, reason, stored = _ending_of(press.ending)
        finished = (job_id, "project-1", state, ended.plan_run_id, press.ignore_memo, False)
        delta: dict[str, Any] = {"jobs": set_to((*before["jobs"][:-1], finished))}
        if stored:
            number = sum(run.project_id == "project-1" for run in desk.planning.runs)
            delta["plan_runs"] = gained(("project-1", number, "ready" if reason is None else "failed", reason))
        assert_state_delta(before, _flag_view(desk), FLAG_UNIVERSE, delta, strict=True)
        logged = desk.log.fields_of("plan.job.finished")[-1]
        assert (logged["job_id"], logged["ignore_memo"], logged["memo_hit"]) == (job_id, press.ignore_memo, False)
        assert logged["elapsed_ms"] == press.waited_ms, "plan.job.finished counts elapsed time in milliseconds"
        assert round(ended.elapsed_s * 1000) == press.waited_ms, "the poll counts elapsed time in seconds"
        completed = [f for f in desk.log.fields_of("plan.run.completed") if f["plan_run_id"] == ended.plan_run_id]
        expected_completed = [(press.ignore_memo, False)] if stored else []
        assert [(fields["ignore_memo"], fields["memo_hit"]) for fields in completed] == expected_completed


# --------------------------------------------------------------- Stop (US-06b, ADR-015 state table, D60, D133, D136)
STOP_UNIVERSE = {"plan_runs", "plan_job_log", "stopped_logged", "items", "projects"}
OTHER = "project-other"  # its job holds the solver slot, so the stopped one waits for it
MOMENTS = ("queued", "waiting_for_optimizer", "solving", "finalising", "done")
NOT_STOPPABLE = {"finalising", *TERMINAL_STATES}
CANCELLED_MESSAGE = "Stopped - nothing was changed"
STOPPED_TEXT = "stopped before a valid route was found"
WAITED_TOO_LONG = "No valid route found within the time limit - nothing was changed"


@dataclass
class StopDesk:
    """The real job over the doubles, with a second project whose job can hold the solver slot. Each gate is held
    only when the press under test stops there."""

    planning: InMemoryPlanning
    solver: ScriptedTourSolver
    clock: FakeClock
    log: RecordingEventLog
    registry: PlanJobRegistry
    job_log: InMemoryPlanJobLog
    gates: dict[str, Gate]

    def view(self) -> dict[str, Any]:
        snapshot = self.planning.snapshots[PROJECT]
        rows = (entry.columns() for entry in self.job_log.rows)
        return {
            "plan_runs": tuple(
                (run.number, run.status, run.failure_reason, run.reproducible, run.not_fully_optimised)
                for run in self.planning.runs
                if run.project_id == PROJECT
            ),
            "plan_job_log": tuple(
                tuple(row[name] for name in LOG_ROW_KEY) for row in rows if row["project_id"] == PROJECT
            ),
            "stopped_logged": tuple(
                (fields["job_id"], fields["project_id"], fields["state"])
                for fields in self.log.fields_of("plan.job.stopped")
            ),
            "items": tuple(item.id for item in snapshot.items),
            "projects": (PROJECT, self.planning.stamps[PROJECT], snapshot.start_item_id, snapshot.end_item_id),
        }

    def start(self, project_id: str) -> str:
        job_id = self.registry.start(project_id)
        assert job_id is not None, f"the job of {project_id} did not start"
        return job_id

    def until_state(self, job_id: str, state: str) -> None:
        _until(lambda: known_job(self.registry, job_id).state == state, f"job in {state}")


def _stop_desk(trip: Trip, moment: str, incumbents: tuple[Incumbent, ...], limits: SolveLimits) -> StopDesk:
    gates = {
        "queued": Gate(held=moment == "queued"),
        "solving": Gate(held=moment in ("solving", "waiting_for_optimizer")),
        "finalising": Gate(held=moment == "finalising"),
    }
    planning = InMemoryPlanning(reading=gates["queued"], storing=gates["finalising"])
    planning.add_project(PROJECT, trip.snapshot)
    planning.add_project(OTHER, trip.snapshot)
    solver = ScriptedTourSolver(None, gate=gates["solving"], incumbents=incumbents)
    clock, log, files = FakeClock(), RecordingEventLog(), InMemoryFileStore()
    trip.seed_canonical_files(files)
    job = PlanRequestJob(
        planning.unit_of_work,
        LegResolver(RecordingRoadMap(trip.leg_m)),
        solver,
        BUDGET,
        clock,
        log,
        files,
        limits=limits,
    )
    job_log = InMemoryPlanJobLog(planning)
    registry = PlanJobRegistry(clock, job, log, job_log=job_log)
    return StopDesk(planning, solver, clock, log, registry, job_log, gates)


def _incumbents_of(trip: Trip) -> st.SearchStrategy[tuple[Incumbent, ...]]:
    order = st.permutations([item.id for item in trip.items]).map(lambda inner: (trip.start.id, *inner, trip.end.id))
    found = st.builds(Incumbent, order=order, objective=st.integers(1, 10**6).map(float))
    return st.lists(found, max_size=2).map(tuple)


def _stopped_ending(moment: str, incumbents: tuple[Incumbent, ...]) -> tuple[Any, ...]:
    """ADR-015's table: the job's (state, reason, message, run) for the moment of the first Stop, `run` as the view
    shows it or `None`. Before solving: cancelled, no run (D133); solving: the best so far, labelled, or Failed
    `stopped` without one (D60, D122); finalising and done: the run being written, unchanged (D136)."""
    if moment in ("queued", "waiting_for_optimizer"):
        return "cancelled", "stopped", CANCELLED_MESSAGE, None
    if moment == "solving" and incumbents:
        return "done", None, None, (1, "ready", None, False, "stopped")
    if moment == "solving":
        return "done", "stopped", STOPPED_TEXT, (1, "failed", "stopped", False, None)
    return "done", None, None, (1, "ready", None, True, None)


def _reach(desk: StopDesk, moment: str) -> str:
    """Starts the job under test and returns its id once it is at `moment`."""
    if moment == "waiting_for_optimizer":
        desk.start(OTHER)
        assert desk.gates["solving"].reached.wait(MAX_WAIT_S), "the other project's job never reached the solver"
        job_id = desk.start(PROJECT)
        desk.until_state(job_id, "waiting_for_optimizer")
        return job_id
    job_id = desk.start(PROJECT)
    if moment == "done":
        job_when_ended(desk.registry, job_id)
        return job_id
    assert desk.gates[moment].reached.wait(MAX_WAIT_S), f"the job never reached {moment}"
    return job_id


@settings(deadline=None, max_examples=60)
@given(trip=trips(), data=st.data(), moment=st.sampled_from(MOMENTS), repeats=st.integers(1, 3))
def test_a_stop_ends_the_job_as_the_state_table_names_and_every_stop_answers_the_current_payload(
    trip: Trip, data: st.DataObject, moment: str, repeats: int
) -> None:
    incumbents = data.draw(_incumbents_of(trip), label="incumbents") if moment == "solving" else ()
    desk = _stop_desk(trip, moment, incumbents, SolveLimits())
    before = desk.view()
    job_id = _reach(desk, moment)
    at_the_stop = known_job(desk.registry, job_id)

    answers = [desk.registry.stop(job_id) for _ in range(repeats)]
    for gate in desk.gates.values():
        gate.release()
    ended = job_when_ended(desk.registry, job_id)

    state, reason, message, run = _stopped_ending(moment, incumbents)
    assert (ended.state, ended.reason, ended.message) == (state, reason, message)
    assert (ended.plan_run_id is not None) == (run is not None), f"a run is named iff one is stored: {ended}"
    assert not ended.stoppable, "an ended job is not stoppable"
    for answer in answers:
        assert answer is not None, "a known job's Stop answers its payload"
        assert answer in (at_the_stop, ended), f"a Stop answered neither the payload at the stop nor the end: {answer}"
        assert answer.stoppable == (answer.state not in NOT_STOPPABLE), f"stoppable before finalising only: {answer}"
    assert at_the_stop.state == moment and at_the_stop.stoppable == (moment not in NOT_STOPPABLE)
    stopped = moment not in ("finalising", "done")
    _until(lambda: len(desk.job_log.rows) == (2 if moment == "waiting_for_optimizer" else 1), "every job's row")
    assert_state_delta(
        before,
        desk.view(),
        STOP_UNIVERSE,
        {
            "plan_runs": gained(run) if run is not None else set_to(()),
            "plan_job_log": gained((job_id, PROJECT, state, ended.plan_run_id, reason, None)),
            "stopped_logged": gained((job_id, PROJECT, moment)) if stopped else set_to(()),
        },
        strict=True,
    )
    assert desk.registry.stop("not-a-job") is None, "an unknown job's Stop answers nothing (404)"
    desk.clock.advance(KEPT_FOR_S)
    assert desk.registry.stop(job_id) is None, "an expired job's Stop answers nothing (404)"


@pytest.mark.heavy_property  # over 5 s at profile ci on the Mac, about 2.5x that on a runner: slow-properties job
@settings(deadline=None, max_examples=10)
@given(trip=trips(), feasibility=st.integers(1, 600), longer=st.integers(0, 1200))
def test_a_job_waiting_for_the_optimizer_gives_up_at_the_feasibility_limit_counted_from_its_start(
    trip: Trip, feasibility: int, longer: int
) -> None:
    desk = _stop_desk(trip, "waiting_for_optimizer", (), SolveLimits(feasibility, feasibility + longer))
    before = desk.view()
    job_id = _reach(desk, "waiting_for_optimizer")

    desk.clock.advance(feasibility - 1)
    time.sleep(0.3)  # longer than the slot wait's step: a wait that gave up early would show by now
    still = known_job(desk.registry, job_id)
    desk.clock.advance(1)
    ended = job_when_ended(desk.registry, job_id)
    desk.gates["solving"].release()

    assert (still.state, still.stoppable) == ("waiting_for_optimizer", True)
    assert (ended.state, ended.reason, ended.message, ended.plan_run_id) == (
        "timed_out",
        "timeout",
        WAITED_TOO_LONG,
        None,
    )
    assert ended.elapsed_s == feasibility
    _until(lambda: len(desk.job_log.rows) == 2, "every job's row")
    assert_state_delta(
        before,
        desk.view(),
        STOP_UNIVERSE,
        {"plan_job_log": gained((job_id, PROJECT, "timed_out", None, "timeout", None))},
        strict=True,
    )


# --------------------------------------- Stop and the feasibility limit during the road look-up (06-09, ADR-015, D157)
LOOK_UP_UNIVERSE = STOP_UNIVERSE | {"road_map.asked"}
LOOK_UP_ENDINGS = {
    "stop": ("cancelled", "stopped", CANCELLED_MESSAGE),
    "feasibility_limit": ("timed_out", "timeout", WAITED_TOO_LONG),
}


class _HeldAtCall(Gate):
    """Lets the first `free` road-map calls through and holds the next one until the test releases it."""

    def __init__(self, free: int) -> None:
        super().__init__(held=True)
        self._free = free

    def passing(self) -> None:
        if self._free > 0:
            self._free -= 1
            return
        super().passing()


def _calls_of(trip: Trip) -> dict[Any, list[Any]]:
    """The road-map calls of the trip's look-up: one per origin with a road to drive, all of its targets (L5)."""
    calls: dict[Any, list[Any]] = {}
    for pair in dict.fromkeys(SolverModelBuilder(trip.snapshot).required_pairs()):
        if pair[0] != pair[1]:
            calls.setdefault(pair[0], []).append(pair)
    return calls


def _look_up_view(desk: StopDesk, road_map: RecordingRoadMap) -> dict[str, Any]:
    return {**desk.view(), "road_map.asked": Counter(road_map.asked)}


def _asked_after_the_ending(late: set[Any], missing: set[Any]) -> Callable[[Any, Any], bool]:
    """The late call's pairs once, and again by the next job if it read the cache before the late answer was kept;
    every other pair still missing, once."""

    def _predicate(old: Counter[Any], new: Counter[Any]) -> bool:
        asked = new - old
        late_ok = all(asked[pair] in (1, 2) for pair in late)
        return (
            old <= new
            and late_ok
            and {pair: n for pair, n in asked.items() if pair not in late} == dict.fromkeys(missing, 1)
        )

    _predicate.__name__ = "asked_after_the_ending"
    return _predicate


@settings(deadline=None, max_examples=20)
@given(
    trip=trips(),
    data=st.data(),
    ending=st.sampled_from(sorted(LOOK_UP_ENDINGS)),
    feasibility=st.integers(1, 600),
)
def test_a_stop_or_the_feasibility_limit_during_the_road_look_up_ends_the_job_at_once_with_no_run_and_keeps_the_legs(
    trip: Trip, data: st.DataObject, ending: str, feasibility: int
) -> None:
    calls = list(_calls_of(trip).values())
    assume(calls)
    held_at = data.draw(st.integers(0, len(calls) - 1), label="the road-map call under way at the ending")
    road_map = RecordingRoadMap(trip.leg_m, gate=_HeldAtCall(held_at))
    desk = _look_up_desk(trip, road_map, SolveLimits(feasibility, feasibility))
    distinct = set(SolverModelBuilder(trip.snapshot).required_pairs())
    roads = {pair for call in calls for pair in call}
    found = {pair for call in calls[:held_at] for pair in call}  # answered before the ending
    before = _look_up_view(desk, road_map)

    job_id = desk.start(PROJECT)
    assert road_map.gate.reached.wait(MAX_WAIT_S), "the look-up never reached the held road-map call"
    looking_up = known_job(desk.registry, job_id)
    if ending == "stop":
        desk.registry.stop(job_id)
    else:
        desk.clock.advance(feasibility)
    ended = job_when_ended(desk.registry, job_id)  # while the road-map call is still under way

    state, reason, message = LOOK_UP_ENDINGS[ending]
    assert (looking_up.state, looking_up.legs_new, looking_up.legs_cached) == (
        "computing_legs",
        len(found),
        len(distinct - roads),
    )
    assert (ended.state, ended.reason, ended.message, ended.plan_run_id) == (state, reason, message, None)
    assert ended.elapsed_s == (feasibility if ending == "feasibility_limit" else 0)
    assert_state_delta(
        before,
        _look_up_view(desk, road_map),
        LOOK_UP_UNIVERSE,
        {
            "plan_job_log": gained((job_id, PROJECT, state, None, reason, None)),
            "stopped_logged": gained((job_id, PROJECT, "computing_legs")) if ending == "stop" else set_to(()),
            "road_map.asked": set_to(Counter(found)),
        },
        strict=True,
    )

    road_map.gate.release()  # the late answer: kept as a leg, never a run
    after_the_ending = _look_up_view(desk, road_map)
    next_id = desk.start(PROJECT)
    recalculated = job_when_ended(desk.registry, next_id)

    assert recalculated.state == "done" and recalculated.legs_cached is not None
    assert recalculated.legs_cached >= len(distinct - roads) + len(found), "the legs found so far were not reused"
    assert recalculated.legs_new + recalculated.legs_cached == len(distinct)
    _until(lambda: len(desk.job_log.rows) == 2, "the next job's row")
    assert_state_delta(
        after_the_ending,
        _look_up_view(desk, road_map),
        LOOK_UP_UNIVERSE,
        {
            "plan_runs": set_to(((1, "ready", None, True, None),)),
            "plan_job_log": gained((next_id, PROJECT, "done", recalculated.plan_run_id, None, None)),
            "road_map.asked": _asked_after_the_ending(set(calls[held_at]), roads - found - set(calls[held_at])),
        },
        strict=True,
    )


def _look_up_desk(trip: Trip, road_map: RecordingRoadMap, limits: SolveLimits) -> StopDesk:
    """The real job and its real resolver over `road_map`; no gate of the desk is held."""
    planning = InMemoryPlanning()
    planning.add_project(PROJECT, trip.snapshot)
    solver = ScriptedTourSolver(None)
    clock, log, files = FakeClock(), RecordingEventLog(), InMemoryFileStore()
    trip.seed_canonical_files(files)
    job = PlanRequestJob(planning.unit_of_work, LegResolver(road_map), solver, BUDGET, clock, log, files, limits=limits)
    job_log = InMemoryPlanJobLog(planning)
    return StopDesk(planning, solver, clock, log, PlanJobRegistry(clock, job, log, job_log=job_log), job_log, {})

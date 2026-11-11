"""How a solve ended decides the run, its flags and its label (ADR-015 table of endings, D122, D42, D223 b, D151).

Driving ports: `PlanJobRegistry` (start, poll) running the real `PlanRequestJob`, and `PlanRunQueries.get`. Driven
ports: `PlanningUnitOfWork` and `PlanJobLog` (in-memory), `TourSolver` (scripted: it streams incumbents to the job's
observer, then ends as scripted, and keeps the deadlines it was handed), `Clock` (fake, moved on before each incumbent).
Observable universe: `plan_runs` as stored and shown (status, reason, order, reproducible, label code, messages),
`job_log` (the job's row: incumbents, reproducible, not_fully_optimised_reason), `poll.incumbent` while solving,
`poll.message` once ended, `solve.deadlines`: the feasibility and optimisation deadlines the solve was handed, in
seconds from the job's start on the `Clock` port (ADR-014 section 2, D58), for any pair of limits, and `stop.answer`:
the state and `stoppable` a Stop pressed while solving answers (D136), null when nobody pressed it. A Stop while solving
reaches the solve through the port's stop signal (brief section 6) and ends it like the adapter does: the last incumbent
labelled `stopped`, or Failed `stopped` without one (ADR-015, D122). A ready run's lines start with its run time line
(06-10), checked here by its pattern; its words are test_run_messages'.
Test Budget: 4 behaviors (an ending gives exactly one run with the flags, lines and job message of that ending;
incumbents show on the poll and are counted in the job's row; the solve gets the limits as deadlines from job start;
a Stop while solving ends the solve through its stop signal with the best so far) x 2 = 8; 1 property test used, every
behavior on every example (D212). Unreachable items (07-05): one more behavior (an Included item no order can connect
fails the run before the solver is asked, naming it; otherwise the solver is asked) x 2 = 2; 1 property test used.
The label texts are written here as the product shows them, not imported.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.application.planning.facade import PlanJobRegistry, PlanRequestJob, PlanRunQueries
from overland_planner.application.ports.plan_run_repository import NewPlanRun
from overland_planner.application.ports.tour_solver import (
    Incumbent,
    SolveLimits,
    TourFound,
    TourNoRoute,
    TourOptimizerFailed,
    TourOutcome,
    TourTimedOut,
)
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.application.planning.planning_doubles import (
    Gate,
    InMemoryPlanJobLog,
    InMemoryPlanning,
    RecordingRoadMap,
    job_when_ended,
    known_job,
)
from tests.unit.application.planning.scripted_tour_solver import ScriptedTourSolver
from tests.unit.domain.planning.trips import POINT_PAIRS, PROJECT, Trip, left_at, reached_at, trips

UNIVERSE = {"plan_runs", "job_log", "poll.incumbent", "poll.message", "solve.deadlines", "stop.answer"}
BUDGET = 500
EVERY_S = 1.5  # the fake clock moves on this much before each incumbent
CRASH_LABEL = ("not fully optimised (optimizer failed)",)
TIME_LIMIT_LABEL = ("not fully optimised (time limit)",)
TIMEOUT_TEXT = "No valid route found within the time limit - plan run #1 failed"
STOPPED_LABEL = ("not fully optimised (stopped)",)
STOPPED_TEXT = "stopped before a valid route was found"
RUN_TIME = r" (?:\d+ h )?(?:\d+ min )?\d+(?:\.\d+)? s"  # the acceptance binding's pattern
NOT_AN_ITEM = "reversed:item"
FAILED = "optimizer_failed"


@dataclass(frozen=True)
class Ending:
    """A scripted solve: what it streams, how it ends, and the run, row and label that ending must give."""

    incumbents: tuple[Incumbent, ...]
    outcome: TourOutcome
    run: tuple[Any, ...]
    row: tuple[Any, ...]
    message: str | None = None
    stopped: bool = False  # Marco presses Stop while the solve runs; the scripted outcome is then never reached


@st.composite
def endings(draw: st.DrawFn, trip: Trip) -> Ending:
    def an_order() -> tuple[str, ...]:
        return (trip.start.id, *draw(st.permutations([item.id for item in trip.items])), trip.end.id)

    objectives = sorted(draw(st.lists(st.integers(1, 10**7), unique=True, max_size=3)), reverse=True)
    incumbents = tuple(Incumbent(order=an_order(), objective=objective) for objective in objectives)
    count = len(incumbents)
    kind = draw(
        st.sampled_from(
            ["budget", "crash_after", "crash_before", "no_route", "time_limit", "timeout", "broken_order", "stop"]
        )
    )
    if kind == "stop" and incumbents:  # the best so far: the last incumbent, labelled, not reproducible (D60)
        order = incumbents[-1].order
        run = (1, "ready", None, order, False, "stopped", STOPPED_LABEL)
        return Ending(incumbents, TourFound(an_order()), run, ("done", count, False, "stopped"), stopped=True)
    if kind == "stop":
        run = (1, "failed", "stopped", (), False, None, (STOPPED_TEXT,))
        return Ending((), TourFound(an_order()), run, ("done", 0, False, None), STOPPED_TEXT, stopped=True)
    if kind == "budget":
        order = an_order()
        return Ending(
            incumbents, TourFound(order), (1, "ready", None, order, True, None, ()), ("done", count, True, None)
        )
    if kind == "crash_after" and incumbents:
        order = incumbents[-1].order
        outcome: TourOutcome = TourFound(order, ending="optimizer_failed")
        run = (1, "ready", None, order, False, "optimizer_failed", CRASH_LABEL)
        return Ending(incumbents, outcome, run, ("done", count, False, "optimizer_failed"))
    if kind in ("crash_after", "crash_before"):
        exit_code, signal = draw(st.sampled_from([(3, None), (None, 9), (1, None)]))
        run = (1, "failed", "optimizer_failed", (), False, None, ())
        return Ending((), TourOptimizerFailed(exit_code, signal), run, ("done", 0, False, None))
    if kind == "no_route":
        run = (1, "failed", "no_valid_route_found", (), True, None, ())
        return Ending((), TourNoRoute(), run, ("done", 0, True, None))
    if kind == "time_limit" and incumbents:  # the optimisation limit with an incumbent: the last one, labelled
        order = incumbents[-1].order
        run = (1, "ready", None, order, False, "time_limit", TIME_LIMIT_LABEL)
        return Ending(incumbents, TourFound(order, ending="time_limit"), run, ("done", count, False, "time_limit"))
    if kind in ("time_limit", "timeout"):  # the feasibility limit without one
        run = (1, "failed", "timeout", (), False, None, (TIMEOUT_TEXT,))
        return Ending((), TourTimedOut(), run, ("done", 0, False, None), TIMEOUT_TEXT)
    # the chosen order breaks a rule: Failed, never an earlier valid incumbent instead (ADR-015, no fallback)
    broken = TourFound((trip.start.id, NOT_AN_ITEM, trip.end.id), ending=draw(st.sampled_from(["budget", FAILED])))
    reproducible = broken.ending == "budget"
    run = (1, "failed", "internal_invariant_violation", (), reproducible, None, ())
    return Ending(incumbents, broken, run, ("done", count, reproducible, None))


def _view(
    planning: InMemoryPlanning,
    job_log: InMemoryPlanJobLog,
    poll: Any,
    message: str | None = None,
    deadlines: tuple[float, float] | None = None,
    stop_answer: tuple[str, bool] | None = None,
) -> dict[str, Any]:
    queries = PlanRunQueries(planning.unit_of_work)
    shown = [queries.get(run.id) for run in planning.runs]
    return {
        "plan_runs": tuple(
            (
                run.number,
                run.status,
                run.failure_reason,
                tuple(stop.item_id for stop in run.stops),
                run.reproducible,
                run.not_fully_optimised,
                _after_the_run_time(run, detail.messages) if detail is not None else None,
            )
            for run, detail in zip(planning.runs, shown, strict=True)
        ),
        "job_log": tuple(
            (
                row.fields["terminal_state"],
                row.fields["incumbents"],
                row.fields["reproducible"],
                row.fields["not_fully_optimised_reason"],
            )
            for row in job_log.rows
        ),
        "poll.incumbent": poll,
        "poll.message": message,
        "solve.deadlines": deadlines,
        "stop.answer": stop_answer,
    }


def _after_the_run_time(run: NewPlanRun, lines: tuple[str, ...]) -> tuple[str, ...]:
    """A ready run's lines after its run time line, which names the Included items it planned."""
    if run.status != "ready":
        return lines
    items = len(run.inputs["included_item_ids"])  # type: ignore[arg-type]
    assert lines and re.fullmatch(rf"Planned {items} items in{RUN_TIME}", lines[0]), f"no run time line: {lines}"
    return lines[1:]


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@settings(deadline=None)
@given(trip=trips(), data=st.data(), feasibility=st.integers(1, 600), longer=st.integers(0, 1800))
def test_how_the_solve_ended_gives_one_run_with_its_flags_and_the_incumbents_show_while_solving(
    trip: Trip, data: st.DataObject, feasibility: int, longer: int
) -> None:
    ending = data.draw(endings(trip), label="ending")
    limits = SolveLimits(feasibility_s=feasibility, optimisation_s=feasibility + longer)
    planning, files, clock = InMemoryPlanning(), InMemoryFileStore(), FakeClock()
    trip.seed_canonical_files(files)
    planning.add_project(PROJECT, trip.snapshot)
    job_log, log = InMemoryPlanJobLog(planning), RecordingEventLog()
    solver = ScriptedTourSolver(
        ending.outcome, gate=Gate(held=True), incumbents=ending.incumbents, clock=clock, incumbent_every_s=EVERY_S
    )
    work = PlanRequestJob(
        planning.unit_of_work,
        LegResolver(RecordingRoadMap(trip.leg_m)),
        solver,
        BUDGET,
        clock,
        log,
        files,
        limits=limits,
    )
    registry = PlanJobRegistry(clock, work, log, job_log=job_log)
    before = _view(planning, job_log, None)

    job_started_s = clock.monotonic()
    job_id = registry.start(PROJECT)
    assert job_id is not None
    assert solver.gate.reached.wait(30.0), "the solve was never asked"
    solving = known_job(registry, job_id)
    answer = registry.stop(job_id) if ending.stopped else None
    solver.gate.release()
    ended = job_when_ended(registry, job_id)
    (handed,) = solver.deadlines
    assert handed is not None, "the solve was handed no deadlines"

    last = ending.incumbents[-1] if ending.incumbents else None
    shown_while_solving = None
    if last is not None:
        found_at_s = EVERY_S * len(ending.incumbents)
        shown_while_solving = {
            "unconfirmed_legs": 0,
            "retraces": 0,
            "objective": last.objective,
            "found_at_s": found_at_s,
        }
    assert solving.state == "solving"
    assert_state_delta(
        before,
        _view(
            planning,
            job_log,
            solving.incumbent,
            ended.message,
            (handed.feasibility_s - job_started_s, handed.optimisation_s - job_started_s),
            None if answer is None else (answer.state, answer.stoppable),
        ),
        UNIVERSE,
        {
            "plan_runs": gained(ending.run),
            "job_log": gained(ending.row),
            "poll.incumbent": set_to(shown_while_solving),
            "poll.message": set_to(ending.message),
            "solve.deadlines": set_to((float(feasibility), float(feasibility + longer))),
            "stop.answer": set_to(("solving", True) if ending.stopped else None),
        },
        strict=True,
    )


# ------------------------------------------------------------ the second pass of the legs (07-03, ADR-017 section 2)
LEGS_UNIVERSE = {"road_map.asked", "job_log.second_pass_pairs", "job_log.legs"}
RoadPairOfPoints = tuple[Coordinate, Coordinate]


def _arcs_of(trip: Trip) -> list[tuple[CatalogItem, CatalogItem]]:
    """Who may be driven after whom, worked out from the brief: Start to each item, each item to every other and to
    End; with no item, Start to End."""
    if not trip.items:
        return [(trip.start, trip.end)]
    sources, targets = [trip.start, *trip.items], [*trip.items, trip.end]
    return [(a, b) for a in sources for b in targets if a is not b]


def _job_view(asked: Counter[RoadPairOfPoints], job_log: InMemoryPlanJobLog, *, ended: bool = False) -> dict[str, Any]:
    fields = job_log.rows[0].fields if ended else {}
    legs = (fields.get("legs_new"), fields.get("legs_cached"), fields.get("legs_total")) if ended else None
    return {
        "road_map.asked": Counter(asked),
        "job_log.second_pass_pairs": fields.get("second_pass_pairs"),
        "job_log.legs": legs,
    }


@settings(deadline=None)
@given(trip=trips(), data=st.data())
def test_the_second_pass_asks_the_retrace_pair_only_where_the_first_pair_has_no_road_and_the_counters_add_up(
    trip: Trip, data: st.DataObject
) -> None:
    no_road = data.draw(st.sets(st.sampled_from(POINT_PAIRS)), label="pairs with no road")
    planning, files, clock = InMemoryPlanning(), InMemoryFileStore(), FakeClock()
    trip.seed_canonical_files(files)
    planning.add_project(PROJECT, trip.snapshot)
    job_log, log = InMemoryPlanJobLog(planning), RecordingEventLog()
    road_map = RecordingRoadMap(trip.leg_m, no_road=no_road)
    work = PlanRequestJob(planning.unit_of_work, LegResolver(road_map), ScriptedTourSolver(), BUDGET, clock, log, files)
    registry = PlanJobRegistry(clock, work, log, job_log=job_log)
    before = _job_view(road_map.asked, job_log)

    job_id = registry.start(PROJECT)
    assert job_id is not None
    job_when_ended(registry, job_id)  # how it ends is the model's (07-04); the legs are asked before that

    first = set(SolverModelBuilder(trip.snapshot).required_pairs())
    second: set[RoadPairOfPoints] = set()
    for previous, successor in _arcs_of(trip):
        leaving = (left_at(previous), reached_at(successor))
        if leaving in no_road and isinstance(previous, TrackItem) and previous.entry != previous.exit:
            second.add((previous.entry, reached_at(successor)))
    fresh = second - first
    every = first | fresh
    asked = Counter({pair: 1 for pair in every if pair[0] != pair[1]})
    new = len(asked)
    assert_state_delta(
        before,
        _job_view(road_map.asked, job_log, ended=True),
        LEGS_UNIVERSE,
        {
            "road_map.asked": set_to(asked),
            "job_log.second_pass_pairs": set_to(len(fresh) or None),  # noted only when a second pass was asked
            "job_log.legs": set_to((new, len(every) - new, len(every))),
        },
        strict=True,
    )


# ------------------------------------------------- an item no order can connect fails the run first (07-05, FR-8.2)
UNREACHABLE_UNIVERSE = {"plan_runs", "projects", "items", "solver_calls", "job.message"}


def _item_failure(number: int, name: str) -> str:
    return f"Plan run #{number} failed: '{name}' cannot be connected to any other stop at any confidence level"


def _connected(trip: Trip, no_road: set[RoadPairOfPoints], origin: CatalogItem, destination: CatalogItem) -> bool:
    """Whether an arc origin -> destination runs, worked out from ADR-017: a road at any level from where origin is left
    to where destination is reached (identical points are one), else, for a track with another end, a road from its
    entry after a retrace."""
    leaving = (left_at(origin), reached_at(destination))
    if leaving[0] == leaving[1] or leaving not in no_road:
        return True
    if not isinstance(origin, TrackItem) or origin.entry == origin.exit:
        return False
    onward = (origin.entry, reached_at(destination))
    return onward[0] == onward[1] or onward not in no_road


def _items_cut_off(trip: Trip, no_road: set[RoadPairOfPoints]) -> list[str]:
    """The names of the Included items that cannot be both entered from the Start and left towards the End, by a closure
    of the arcs written out one by one (Warshall), not by walking from the anchors."""
    visited = trip.snapshot.visited_items()
    nodes = [trip.start, *visited, trip.end]
    last = len(nodes) - 1
    ahead = [[False] * len(nodes) for _ in nodes]
    for origin in range(last):
        for destination in range(1, last + 1):
            direct = (origin, destination) == (0, last) and visited
            if origin != destination and not direct:
                ahead[origin][destination] = _connected(trip, no_road, nodes[origin], nodes[destination])
    for via in range(len(nodes)):
        for origin in range(len(nodes)):
            for destination in range(len(nodes)):
                ahead[origin][destination] |= ahead[origin][via] and ahead[via][destination]
    return [nodes[node].name for node in range(1, last) if not (ahead[0][node] and ahead[node][last])]


@settings(deadline=None)
@given(trip=trips(), data=st.data())
def test_an_item_no_order_can_connect_fails_the_run_naming_it_before_the_solver_is_asked(
    trip: Trip, data: st.DataObject
) -> None:
    no_road = data.draw(st.sets(st.sampled_from(POINT_PAIRS)), label="pairs with no road")
    planning, files, clock = InMemoryPlanning(), InMemoryFileStore(), FakeClock()
    trip.seed_canonical_files(files)
    planning.add_project(PROJECT, trip.snapshot)
    job_log, log = InMemoryPlanJobLog(planning), RecordingEventLog()
    solver = ScriptedTourSolver(TourNoRoute())  # asked, it finds no route: a Failed run, whatever the legs
    work = PlanRequestJob(
        planning.unit_of_work,
        LegResolver(RecordingRoadMap(trip.leg_m, no_road=no_road)),
        solver,
        BUDGET,
        clock,
        log,
        files,
    )
    registry = PlanJobRegistry(clock, work, log, job_log=job_log)

    def view(message: str | None) -> dict[str, Any]:
        return {
            "plan_runs": tuple(_row(run) for run in planning.runs),
            "projects": (planning.snapshots[PROJECT], planning.stamps[PROJECT]),
            "items": planning.snapshots[PROJECT].items,
            "solver_calls": len(solver.models),
            "job.message": message,
        }

    def _row(run: NewPlanRun) -> tuple[Any, ...]:
        if run.failure_reason != "unreachable":
            return (run.number, "reached the solver")
        shown = PlanRunQueries(planning.unit_of_work).get(run.id)
        assert shown is not None and run.report is not None
        assert (run.status, run.stops, run.totals) == ("failed", (), None)
        return (run.number, run.failure_reason, run.report.reason, run.report.items, shown.messages)

    before = view(None)
    job_id = registry.start(PROJECT)
    assert job_id is not None
    ended = job_when_ended(registry, job_id)

    cut_off = _items_cut_off(trip, no_road)
    lines = tuple(_item_failure(1, name) for name in cut_off)
    expected_run = (1, "unreachable", "unreachable", tuple(cut_off), lines) if cut_off else (1, "reached the solver")
    assert_state_delta(
        before,
        view(ended.message),
        UNREACHABLE_UNIVERSE,
        {
            "plan_runs": gained(expected_run),
            "solver_calls": set_to(0 if cut_off else 1),
            "job.message": set_to("; ".join(lines) if cut_off else None),
        },
        strict=True,
    )

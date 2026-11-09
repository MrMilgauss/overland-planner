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
labelled `stopped`, or Failed `stopped` without one (ADR-015, D122).
Test Budget: 4 behaviors (an ending gives exactly one run with the flags, lines and job message of that ending;
incumbents show on the poll and are counted in the job's row; the solve gets the limits as deadlines from job start;
a Stop while solving ends the solve through its stop signal with the best so far) x 2 = 8; 1 property test used, every
behavior on every example (D212). The label texts are written here as the product shows them, not imported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.application.planning.facade import PlanJobRegistry, PlanRequestJob, PlanRunQueries
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
from tests.unit.domain.planning.trips import PROJECT, Trip, trips

UNIVERSE = {"plan_runs", "job_log", "poll.incumbent", "poll.message", "solve.deadlines", "stop.answer"}
BUDGET = 500
EVERY_S = 1.5  # the fake clock moves on this much before each incumbent
CRASH_LABEL = ("not fully optimised (optimizer failed)",)
TIME_LIMIT_LABEL = ("not fully optimised (time limit)",)
TIMEOUT_TEXT = "No valid route found within the time limit - plan run #1 failed"
STOPPED_LABEL = ("not fully optimised (stopped)",)
STOPPED_TEXT = "stopped before a valid route was found"
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
                detail.messages if detail is not None else None,
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

"""Stage timings of a plan job (ADR-015 DV-2, brief section 5, kpi-contracts K5): `stage_ms` on the poll, line and row.

Driving ports: `PlanRequestService` and `PlanJobRegistry` (polling) over the real `PlanRequestJob`, `LegResolver` and
`FingerprintMemo`. Driven ports: `PlanningUnitOfWork`, `RoutingProvider`, `TourSolver` (scripted), `PlanJobLog`,
`EventLog` and `Clock` (`FakeClock`, moved only by the `Taking` gates of the doubles: the snapshot read, each road map
call, the solve and the store). Durations are drawn in 1/1024 s, so the clock adds them exactly and the whole
milliseconds a stage took are known: the duration truncated (a stage never reports more than it took).
Observable universe: the poll's `stage_ms`, `legs_total` and `items_included`, `plan_job_log` and `plan_runs`.
Test Budget: 2 behaviors (an ended job reports each stage it went through in whole ms within its elapsed time, a memo
hit without a solve; a running job shows its stages, legs and items once known) x 2 = 4; 2 used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.application.planning.facade import (
    FingerprintMemo,
    PlanJobRegistry,
    PlanJobView,
    PlanRequestJob,
    PlanRequestService,
)
from overland_planner.application.platform.facade import HealthService
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.application.planning.planning_doubles import (
    MAX_WAIT_S,
    InMemoryPlanJobLog,
    InMemoryPlanning,
    RecordingRoadMap,
    Taking,
    job_when_ended,
    known_job,
)
from tests.unit.application.planning.scripted_tour_solver import SCRIPTED_IDENTITY, ScriptedTourSolver
from tests.unit.domain.planning.trips import PROJECT, Trip, trips

BUDGET = 500
UNIVERSE = {"stage_ms", "legs_total", "items_included", "plan_job_log", "plan_runs"}
SOLVED_STAGES = {"snapshot", "matrix", "reach_model", "solve", "guard_persist"}
TICKS_PER_S = 1024
TIMED = ("snapshot", "matrix", "solve", "guard_persist")


def _ms(ticks: int) -> int:
    """Whole milliseconds of `ticks` 1/1024 s, truncated."""
    return ticks * 1000 // TICKS_PER_S


def _durations() -> st.SearchStrategy[dict[str, int]]:
    return st.fixed_dictionaries({stage: st.integers(0, 60 * TICKS_PER_S) for stage in TIMED})


@dataclass
class TimedPlanner:
    clock: FakeClock
    gates: dict[str, Taking]
    log: RecordingEventLog
    planning: InMemoryPlanning
    job_log: InMemoryPlanJobLog
    registry: PlanJobRegistry
    service: PlanRequestService

    def view(self, job_id: str | None) -> dict[str, Any]:
        job = None if job_id is None else known_job(self.registry, job_id)
        return {
            "stage_ms": None if job is None else job.stage_ms,
            "legs_total": None if job is None else job.legs_total,
            "items_included": None if job is None else job.items_included,
            "plan_job_log": tuple((entry.fields["job_id"], entry.fields["memo_hit"]) for entry in self.job_log.rows),
            "plan_runs": tuple((run.number, run.status) for run in self.planning.runs),
        }

    def took_ms(self, stage: str, ticks: int) -> int:
        """What the doubles of `stage` took on the clock so far, in a single job."""
        return _ms(ticks * self.gates[stage].passings)


def _timed_planner(trip: Trip, ticks: dict[str, int], *, held_at: str | None = None) -> TimedPlanner:
    clock = FakeClock()
    gates = {
        stage: Taking(clock, ticks[stage] / TICKS_PER_S, free=1 if stage == "snapshot" else 0, held=stage == held_at)
        for stage in TIMED
    }  # the snapshot gate lets the request's own pre-check read through
    planning = InMemoryPlanning(reading=gates["snapshot"], storing=gates["guard_persist"])
    planning.add_project(PROJECT, trip.snapshot)
    files = InMemoryFileStore()
    trip.seed_canonical_files(files)
    log = RecordingEventLog()
    road_map = RecordingRoadMap(trip.leg_m, gate=gates["matrix"])
    solver = ScriptedTourSolver(None, gate=gates["solve"])
    memo = FingerprintMemo(SCRIPTED_IDENTITY)
    job = PlanRequestJob(planning.unit_of_work, LegResolver(road_map), solver, BUDGET, clock, log, files, memo)
    job_log = InMemoryPlanJobLog(planning)
    registry = PlanJobRegistry(clock, job, log, job_log=job_log)
    service = PlanRequestService(
        planning.unit_of_work, HealthService({"tour_solver": ProbeResult("ok")}), log, registry
    )
    return TimedPlanner(clock, gates, log, planning, job_log, registry, service)


def _known_counts(trip: Trip) -> tuple[int, int]:
    """The distinct road legs the job asks for, and the items its model includes: Start, End and the Included."""
    legs = len(set(SolverModelBuilder(trip.snapshot).required_pairs()))
    return legs, len({trip.start.id, trip.end.id, *(item.id for item in trip.items)})


def _assert_reported_alike(planner: TimedPlanner, job: PlanJobView) -> None:
    """The poll, the `plan.job.finished` line and the row show the same `stage_ms` within the elapsed time."""
    line = planner.log.fields_of("plan.job.finished")[-1]
    row = planner.job_log.rows[-1].columns()
    stage_ms = job.stage_ms or {}
    assert line["stage_ms"] == row["stage_ms"] == stage_ms
    assert all(isinstance(ms, int) and ms >= 0 for ms in stage_ms.values()), f"not whole ms: {stage_ms}"
    assert sum(stage_ms.values()) <= line["elapsed_ms"] == row["elapsed_ms"]
    assert sum(stage_ms.values()) <= job.elapsed_s * 1000


def _ended_with_stages(planner: TimedPlanner, ticks: dict[str, int]) -> tuple[str, PlanJobView, dict[str, int]]:
    """Press Calculate and wait for the end; the stages the job went through, as the doubles took them: one snapshot
    read, the road map calls of this job (none for legs already resolved), one solve unless reused, one store."""
    road_map_calls, solves = planner.gates["matrix"].passings, planner.gates["solve"].passings
    job_id = planner.service.request(PROJECT)
    job = job_when_ended(planner.registry, job_id)
    road_map_calls = planner.gates["matrix"].passings - road_map_calls
    solved = planner.gates["solve"].passings - solves
    stages = {
        "snapshot": _ms(ticks["snapshot"]),
        "matrix": _ms(ticks["matrix"] * road_map_calls),
        "reach_model": 0,
        "guard_persist": _ms(ticks["guard_persist"]),
    }
    return job_id, job, stages | ({"solve": _ms(ticks["solve"])} if solved else {})


@settings(deadline=None)
@given(trip=trips(), ticks=_durations(), again=st.booleans())
def test_an_ended_job_reports_each_stage_in_whole_ms_within_its_elapsed_time_and_a_memo_hit_no_solve(
    trip: Trip, ticks: dict[str, int], again: bool
) -> None:
    planner = _timed_planner(trip, ticks)
    legs_total, items_included = _known_counts(trip)
    before = planner.view(None)

    job_id, job, expected = _ended_with_stages(planner, ticks)
    assert set(expected) == SOLVED_STAGES
    _assert_reported_alike(planner, job)
    rows, runs = [(job_id, False)], [(1, "ready")]
    if again:  # the memo gives the order: the solver is not asked and reports no solve
        job_id, job, expected = _ended_with_stages(planner, ticks)
        assert job.memo_hit and set(expected) == SOLVED_STAGES - {"solve"}
        _assert_reported_alike(planner, job)
        rows.append((job_id, True))
        runs.append((2, "ready"))

    assert_state_delta(
        before,
        planner.view(job_id),
        UNIVERSE,
        {
            "stage_ms": set_to(expected),
            "legs_total": set_to(legs_total),
            "items_included": set_to(items_included),
            "plan_job_log": gained(*rows),
            "plan_runs": gained(*runs),
        },
        strict=True,
    )


@settings(deadline=None)
@given(trip=trips(), ticks=_durations(), held_at=st.sampled_from(["matrix", "solve"]))
def test_a_running_job_shows_its_finished_stages_and_its_legs_and_items_once_known(
    trip: Trip, ticks: dict[str, int], held_at: str
) -> None:
    planner = _timed_planner(trip, ticks, held_at=held_at)
    legs_total, items_included = _known_counts(trip)
    asks_the_road_map = any(
        origin != destination for origin, destination in SolverModelBuilder(trip.snapshot).required_pairs()
    )
    if held_at == "matrix" and not asks_the_road_map:
        held_at = "solve"  # legs between identical points need no road map
        planner = _timed_planner(trip, ticks, held_at=held_at)
    before = planner.view(None)

    job_id = planner.service.request(PROJECT)
    assert planner.gates[held_at].reached.wait(MAX_WAIT_S), f"the job never reached {held_at}"
    running = planner.view(job_id)
    planner.gates[held_at].release()
    job_when_ended(planner.registry, job_id)

    if held_at == "matrix":
        expected = {"stage_ms": set_to({"snapshot": planner.took_ms("snapshot", ticks["snapshot"])})}
    else:
        expected = {
            "stage_ms": set_to(
                {stage: planner.took_ms(stage, ticks[stage]) for stage in ("snapshot", "matrix")} | {"reach_model": 0}
            ),
            "legs_total": set_to(legs_total),
            "items_included": set_to(items_included),
        }
    assert_state_delta(before, running, UNIVERSE, expected, strict=True)

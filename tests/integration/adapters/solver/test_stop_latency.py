"""Stop reaches a terminal job within 5 s (US-06b KPI, ADR-015, D60, D133, D136), on its own clock.

Integration level: single examples verify the wiring of Stop from the plan job registry through the real
`PlanRequestJob` and the production `OrToolsTourSolver` parent to a spawned child. The child is scripted and deaf to
SIGTERM, so the parent must end it with SIGKILL after its grace (the slowest Stop there is). The `Clock` is a
`FakeClock` that never moves, so no limit can end a solve here: only Stop does. Each test measures from the Stop call to
the first poll that shows the job ended, and checks the child is gone.

The child entry point is module-level so the spawn context can import it in the child.
"""

from __future__ import annotations

import functools
import os
import signal
import time
from multiprocessing.connection import Connection
from pathlib import Path

import pytest

from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from overland_planner.adapters.solver.tour_child import INCUMBENT
from overland_planner.application.planning.facade import PlanJobRegistry, PlanJobView, PlanRequestJob
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.solver_model_builder import TourModel
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.unit.application.planning.planning_doubles import InMemoryPlanning, RecordingRoadMap, known_job
from tests.unit.domain.planning.trips import POINT_PAIRS, POINTS, PROJECT

pytestmark = pytest.mark.solver_child

STOP_KPI_S = 5.0  # US-06b: a Stop reaches a terminal job within 5 s
CHILD_LIFE_S = 30.0  # a deaf child that was never ended ends itself, so none outlives the test run
GIVEN_S = 30.0  # spawning the child and reaching the moment of the Stop; not measured
OTHER = "project-other"
TERMINAL = {"done", "failed", "cancelled", "timed_out"}


def deaf_child(
    answer: Connection, model: TourModel, budget: int, time_limit_s: float, *, incumbent: bool, ready: str
) -> None:
    """Ignores SIGTERM, sends one valid incumbent if asked, says it is ready (its pid in `ready`), then keeps
    "searching" without a final message."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if incumbent:
        middle = [node for node in range(len(model.node_item_ids)) if node not in (model.start_node, model.end_node)]
        answer.send((INCUMBENT, (model.start_node, *middle, model.end_node), 1_000.0))
    Path(ready).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(CHILD_LIFE_S)


class Desk:
    """Two projects of three places each, planned by the production solver parent with a deaf child."""

    def __init__(self, tmp_path: Path, *, incumbent: bool) -> None:
        self.planning = InMemoryPlanning()
        start = PoiItem(id="start", project_id=PROJECT, name="Casa Marco", location=POINTS[0])
        end = PoiItem(id="end", project_id=PROJECT, name="Briancon", location=POINTS[1])
        col = PoiItem(id="col", project_id=PROJECT, name="Strada dell'Assietta", location=POINTS[2])
        for project_id in (PROJECT, OTHER):
            self.planning.add_project(project_id, ProjectSnapshot(start.id, end.id, (start, col, end)))
        self.ready = tmp_path / "ready"
        child = functools.partial(deaf_child, incumbent=incumbent, ready=str(self.ready))
        solver = OrToolsTourSolver(tour_child_main=child)  # type: ignore[arg-type]
        leg_m = {pair: number * 1_000 for number, pair in enumerate(POINT_PAIRS, start=1)}
        clock, log = FakeClock(), RecordingEventLog()
        job = PlanRequestJob(
            self.planning.unit_of_work,
            LegResolver(RecordingRoadMap(leg_m)),
            solver,
            500,
            clock,
            log,
            InMemoryFileStore(),
        )
        self.registry = PlanJobRegistry(clock, job, log)

    def start(self, project_id: str) -> str:
        job_id = self.registry.start(project_id)
        assert job_id is not None
        return job_id

    def until(self, job_id: str, reached: object, what: str) -> PlanJobView:
        deadline = time.monotonic() + GIVEN_S
        while True:
            job = known_job(self.registry, job_id)
            if reached(job):  # type: ignore[operator]
                return job
            assert time.monotonic() < deadline, f"never {what}: {job}"
            time.sleep(0.01)

    def child_ready(self) -> int:
        deadline = time.monotonic() + GIVEN_S
        while not self.ready.exists() or not self.ready.read_text(encoding="utf-8"):
            assert time.monotonic() < deadline, "the solver child never started"
            time.sleep(0.01)
        pid = int(self.ready.read_text(encoding="utf-8"))
        self.ready.unlink()
        return pid

    def stopped_within(self, job_id: str) -> tuple[PlanJobView, float]:
        """Presses Stop and polls until the job ended: the ended job and the seconds from the Stop call."""
        pressed = time.monotonic()
        answer = self.registry.stop(job_id)
        assert answer is not None and answer.stoppable, f"the Stop did not answer a stoppable job: {answer}"
        ended = self.until(job_id, lambda job: job.state in TERMINAL, "ended after the Stop")
        return ended, time.monotonic() - pressed

    def runs(self, project_id: str) -> list[tuple[object, ...]]:
        return [
            (run.status, run.failure_reason, run.reproducible, run.not_fully_optimised)
            for run in self.planning.runs
            if run.project_id == project_id
        ]


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_a_stop_while_solving_with_a_valid_route_ends_the_job_within_5_s_with_it(tmp_path: Path) -> None:
    desk = Desk(tmp_path, incumbent=True)
    job_id = desk.start(PROJECT)
    pid = desk.child_ready()
    desk.until(job_id, lambda job: job.incumbent is not None, "showed the valid route")

    ended, took_s = desk.stopped_within(job_id)

    assert took_s <= STOP_KPI_S, f"the Stop took {took_s:.2f} s"
    assert (ended.state, ended.reason, ended.plan_run_id is not None) == ("done", None, True)
    assert desk.runs(PROJECT) == [("ready", None, False, "stopped")]
    assert _gone(pid), "the solver child outlived the Stop"


def test_a_stop_while_solving_without_a_valid_route_ends_the_job_within_5_s_failed(tmp_path: Path) -> None:
    desk = Desk(tmp_path, incumbent=False)
    job_id = desk.start(PROJECT)
    pid = desk.child_ready()

    ended, took_s = desk.stopped_within(job_id)

    assert took_s <= STOP_KPI_S, f"the Stop took {took_s:.2f} s"
    assert (ended.state, ended.reason, ended.message) == ("done", "stopped", "stopped before a valid route was found")
    assert desk.runs(PROJECT) == [("failed", "stopped", False, None)]
    assert _gone(pid), "the solver child outlived the Stop"


def test_a_stop_while_waiting_for_the_optimizer_ends_the_job_within_5_s_and_the_solve_goes_on(tmp_path: Path) -> None:
    desk = Desk(tmp_path, incumbent=False)
    solving = desk.start(OTHER)
    pid = desk.child_ready()
    waiting = desk.start(PROJECT)
    desk.until(waiting, lambda job: job.state == "waiting_for_optimizer", "waited for the optimizer")

    ended, took_s = desk.stopped_within(waiting)

    assert took_s <= STOP_KPI_S, f"the Stop took {took_s:.2f} s"
    assert (ended.state, ended.message, ended.plan_run_id) == ("cancelled", "Stopped - nothing was changed", None)
    assert (known_job(desk.registry, solving).state, _gone(pid)) == ("solving", False), "the other solve was ended"
    assert desk.runs(PROJECT) == []
    other, took_s = desk.stopped_within(solving)
    assert (other.state, took_s <= STOP_KPI_S, _gone(pid)) == ("done", True, True)

"""A tour solved by OR-Tools in a child process (ADR-014 budget, ADR-015 solver child, D122 reason codes, D200 bound).

Integration level: single examples verify wiring against real spawned children, real OR-Tools and real signals. Every
expected order comes from an enumeration of the model's tours, not from the solver. What each child observation means
lives in tests/unit/adapters/solver/test_tour_outcome.py.

The faulty child entry points are module-level so the spawn context can import them in the child.
"""

from __future__ import annotations

import errno
import itertools
import multiprocessing
import os
import random
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path

import pytest

from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from overland_planner.adapters.solver.tour_child import FINAL, run_tour_child
from overland_planner.application.ports.tour_solver import (
    Incumbent,
    TourFound,
    TourNoRoute,
    TourOptimizerFailed,
    TourTimedOut,
)
from overland_planner.domain.planning.solver_model_builder import TourModel
from tests.common.workspace import workspace_data_dir

pytestmark = pytest.mark.solver_child

REPO_ROOT = Path(__file__).resolve().parents[4]
PID_FILE_VARIABLE = "TOUR_CHILD_TEST_PID_FILE"
ENOUGH_BUDGET = 500
DEFAULT_BUDGET = 10_000
SIGTERM_GRACE_S = 2.0
SIGTERM_IGNORING_CHILD_LIVES_S = 60.0
SIGKILL_SLACK_S = 15.0  # room for a loaded machine, and still far short of the 60 s life of the children left running
N = None

# The cheapest first arc (Start to a) leads into dear arcs, so the first solution is not the best one.
_TRAP_COSTS: tuple[tuple[int | None, ...], ...] = (
    (N, 1, 5, 40, 40, N),
    (N, N, 50, 50, 50, 5),
    (N, 40, N, 5, 40, 40),
    (N, 40, 40, N, 5, 40),
    (N, 5, 40, 40, N, 40),
    (N, N, N, N, N, N),
)
ROUND_TRIP = TourModel(("base", "a", "b", "c", "d", "base"), 0, 5, _TRAP_COSTS)
# The same costs one-way, with the arc b -> c that the best tour would use forbidden, and c -> a cheaper so that one
# best tour remains.
_ONE_WAY_CHANGES: dict[tuple[int, int], int | None] = {(2, 3): N, (3, 1): 30}
_ONE_WAY_COSTS = tuple(
    tuple(_ONE_WAY_CHANGES.get((origin, destination), cost) for destination, cost in enumerate(row))
    for origin, row in enumerate(_TRAP_COSTS)
)
ONE_WAY = TourModel(("start", "a", "b", "c", "d", "end"), 0, 5, _ONE_WAY_COSTS)
# Item b has no arc into it, but every node still has somewhere to go.
NO_WAY_INTO_AN_ITEM = TourModel(("s", "a", "b", "e"), 0, 3, ((N, 5, N, N), (N, N, N, 5), (N, N, N, 5), (N, N, N, N)))
# The Start has nowhere to go at all.
NO_WAY_OUT_OF_START = TourModel(("s", "a", "e"), 0, 2, ((N, N, N), (N, N, 5), (N, N, N)))


def _complete_model(item_count: int) -> TourModel:
    """Every required arc of a trip with `item_count` items, with fixed varied costs and None where none runs."""
    size = item_count + 2
    last = size - 1
    direct = (0, last)

    def cost(origin: int, destination: int) -> int | None:
        runs = origin != last and destination != 0 and origin != destination
        if not runs or (item_count > 0 and (origin, destination) == direct):
            return None
        return 100 + (origin * 37 + destination * 91) % 900

    ids = tuple(f"node-{node}" for node in range(size))
    costs = tuple(tuple(cost(origin, destination) for destination in range(size)) for origin in range(size))
    return TourModel(ids, 0, last, costs)


def _scattered_model(item_count: int, seed: int) -> TourModel:
    """Every required arc with seeded random costs: unlike `_complete_model`'s, its first solution is not the best."""
    rng = random.Random(seed)  # noqa: S311 - reproducible test costs, not security
    size = item_count + 2
    last = size - 1
    costs = tuple(
        tuple(
            None if destination == 0 or origin in (last, destination) else rng.randint(100, 5_000)
            for destination in range(size)
        )
        for origin in range(size)
    )
    return TourModel(tuple(f"node-{node}" for node in range(size)), 0, last, costs)


def _best_order(model: TourModel) -> tuple[str, ...]:
    """Independent oracle: enumerate every tour from Start to End over the arcs that run."""
    inner = [node for node in range(len(model.node_item_ids)) if node not in (model.start_node, model.end_node)]
    tours = []
    for middle in itertools.permutations(inner):
        path = (model.start_node, *middle, model.end_node)
        arcs = [model.arc_m[a][b] for a, b in itertools.pairwise(path)]
        if None not in arcs:
            tours.append((sum(arc for arc in arcs if arc is not None), path))
    (best_cost, best_path), (runner_up_cost, _) = sorted(tours)[:2]
    assert best_cost < runner_up_cost, "the instance must have a unique optimum"
    return tuple(model.node_item_ids[node] for node in best_path)


def _crashing_child(_answer: Connection, _model: TourModel, _budget: int) -> None:
    os._exit(3)


def _killed_child(_answer: Connection, _model: TourModel, _budget: int) -> None:
    os.kill(os.getpid(), signal.SIGKILL)


def _raising_child(_answer: Connection, _model: TourModel, _budget: int) -> None:
    raise RuntimeError("deliberate failure in the solve child")


def _silent_child(answer: Connection, _model: TourModel, _budget: int) -> None:
    answer.close()


def _garbling_child(answer: Connection, _model: TourModel, _budget: int) -> None:
    answer.send_bytes(b"this is not a pickled message")
    answer.close()


def _hanging_child(_answer: Connection, _model: TourModel, _budget: int) -> None:
    time.sleep(60)


def _final_then_crashing_child(answer: Connection, model: TourModel, _budget: int) -> None:
    answer.send((FINAL, tuple(range(len(model.node_item_ids)))))
    os._exit(3)


def _final_then_hanging_child(answer: Connection, model: TourModel, _budget: int) -> None:
    """A complete answer, then an interpreter teardown that does not finish in time, as on a loaded Pi."""
    answer.send((FINAL, tuple(range(len(model.node_item_ids)))))
    time.sleep(60)


def _sigterm_ignoring_child(_answer: Connection, _model: TourModel, _budget: int) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path(os.environ[PID_FILE_VARIABLE]).touch()  # from here on SIGTERM cannot end this child
    time.sleep(SIGTERM_IGNORING_CHILD_LIVES_S)


def _sigterm_recording_child(_answer: Connection, _model: TourModel, _budget: int) -> None:
    listening = Path(os.environ[PID_FILE_VARIABLE])

    def record_and_exit(_signal_number: int, _frame: object) -> None:
        listening.with_suffix(".received").touch()
        os._exit(0)

    signal.signal(signal.SIGTERM, record_and_exit)
    listening.touch()  # from here on SIGTERM reaches the handler
    time.sleep(60)


def _real_child_reporting_its_pid(answer: Connection, model: TourModel, budget: int) -> None:
    """The real solve, reporting its pid at the search's first solution, so the test kills the parent mid-search.

    The report rides on the solve's own callback, the only one there is: it adds no other handover of the GIL, and a
    solve without that callback never reports.
    """
    from ortools.constraint_solver import pywrapcp

    add_callback = pywrapcp.RoutingModel.AddAtSolutionCallback

    def add_reporting(routing: pywrapcp.RoutingModel, callback: Callable[[], None]) -> None:
        def report_then_call() -> None:
            _report_pid_once(Path(os.environ[PID_FILE_VARIABLE]))
            callback()

        add_callback(routing, report_then_call)

    pywrapcp.RoutingModel.AddAtSolutionCallback = add_reporting
    run_tour_child(answer, model, budget)


def _report_pid_once(pid_file: Path) -> None:
    if not pid_file.exists():
        whole = pid_file.with_suffix(".writing")
        whole.write_text(str(os.getpid()))
        whole.replace(pid_file)


def _child_reporting_its_death_signal(_answer: Connection, _model: TourModel, _budget: int) -> None:
    import ctypes

    pr_get_pdeathsig = 2
    death_signal = ctypes.c_int()
    ctypes.CDLL(None).prctl(pr_get_pdeathsig, ctypes.byref(death_signal))
    Path(os.environ[PID_FILE_VARIABLE]).write_text(str(death_signal.value))


def test_solves_a_small_round_trip() -> None:
    solver = OrToolsTourSolver()

    first_solution = solver.solve(ROUND_TRIP, 1)
    best = solver.solve(ROUND_TRIP, ENOUGH_BUDGET)

    assert best == TourFound(order=_best_order(ROUND_TRIP))
    assert isinstance(best, TourFound)
    assert best.order[0] == best.order[-1] == "base"
    assert sorted(best.visited_item_ids) == ["a", "b", "c", "d"]
    assert isinstance(first_solution, TourFound)
    assert first_solution.order != best.order, "a budget of one solution must stop the search at the first solution"


def test_solves_a_small_one_way_trip() -> None:
    # The probe's timeout must not bound a solve: this one is far shorter than any child spawn.
    outcome = OrToolsTourSolver(timeout_s=0.001).solve(ONE_WAY, ENOUGH_BUDGET)

    assert outcome == TourFound(order=_best_order(ONE_WAY))


def test_the_real_child_streams_only_improving_incumbents_and_ends_on_the_last() -> None:
    """60 items, the size of I1 (whose model needs the whole planning pipeline: its golden order is the
    `golden_order` check, which runs with this streaming on). The search must report more than one tour."""
    streamed: list[Incumbent] = []

    outcome = OrToolsTourSolver().solve(_scattered_model(60, seed=1), ENOUGH_BUDGET, on_incumbent=streamed.append)

    assert isinstance(outcome, TourFound)
    assert outcome.ending == "budget"
    assert len(streamed) > 1, "the search reported no improvement after its first tour"
    objectives = [incumbent.objective for incumbent in streamed]
    assert all(later < earlier for earlier, later in itertools.pairwise(objectives)), f"not improving: {objectives}"
    assert streamed[-1].order == outcome.order, "the final order is not the last incumbent"
    assert {(incumbent.unconfirmed_legs, incumbent.retraces) for incumbent in streamed} == {(0, 0)}


def test_same_budget_gives_the_same_order() -> None:
    solver = OrToolsTourSolver()
    model = _complete_model(30)

    first = solver.solve(model, ENOUGH_BUDGET)

    assert isinstance(first, TourFound)
    assert first == solver.solve(model, ENOUGH_BUDGET)


@pytest.mark.parametrize("item_count", [0, 1, 2])
def test_tiny_trips_finish_on_the_full_budget(item_count: int) -> None:
    model = _complete_model(item_count)

    outcome = OrToolsTourSolver().solve(model, DEFAULT_BUDGET)

    assert isinstance(outcome, TourFound)
    assert outcome.order[0] == "node-0"
    assert outcome.order[-1] == f"node-{item_count + 1}"
    assert sorted(outcome.visited_item_ids) == sorted(model.node_item_ids[1:-1])


@pytest.mark.parametrize(
    ("child", "expected"),
    [
        (_crashing_child, TourOptimizerFailed(exit_code=3, signal=None)),
        (_killed_child, TourOptimizerFailed(exit_code=None, signal=signal.SIGKILL)),
        (_raising_child, TourOptimizerFailed(exit_code=1, signal=None)),
        (_silent_child, TourOptimizerFailed(exit_code=0, signal=None)),
        (_garbling_child, TourOptimizerFailed(exit_code=0, signal=None)),
        (_final_then_crashing_child, TourOptimizerFailed(exit_code=3, signal=None)),
    ],
    ids=["exit-code", "sigkill", "exception", "no-message", "garbled-message", "exit-code-after-the-final"],
)
def test_crashed_child_is_optimizer_failed(child: object, expected: TourOptimizerFailed) -> None:
    outcome = OrToolsTourSolver(tour_child_main=child).solve(ROUND_TRIP, ENOUGH_BUDGET)  # type: ignore[arg-type]

    assert outcome == expected
    assert outcome.reason == "optimizer_failed"


@pytest.mark.parametrize("model", [NO_WAY_INTO_AN_ITEM, NO_WAY_OUT_OF_START], ids=["item-unreachable", "start-stuck"])
def test_no_route_is_reported(model: TourModel) -> None:
    outcome = OrToolsTourSolver().solve(model, ENOUGH_BUDGET)

    assert outcome == TourNoRoute()
    assert outcome.reason == "no_valid_route_found"


def _assert_no_child_left() -> None:
    assert multiprocessing.active_children() == []


def test_a_valid_final_counts_when_the_child_does_not_exit_in_time() -> None:
    outcome = OrToolsTourSolver(tour_child_main=_final_then_hanging_child).solve(ROUND_TRIP, ENOUGH_BUDGET)

    assert outcome == TourFound(order=ROUND_TRIP.node_item_ids)
    _assert_no_child_left()


def test_overrunning_child_is_killed() -> None:
    bound_s = 1.0
    solver = OrToolsTourSolver(tour_child_main=_hanging_child, safety_bound_s=bound_s)

    started = time.monotonic()
    outcome = solver.solve(ROUND_TRIP, ENOUGH_BUDGET)
    elapsed = time.monotonic() - started

    assert outcome == TourTimedOut()
    assert outcome.reason == "timeout"
    assert bound_s <= elapsed < bound_s + SIGKILL_SLACK_S, f"the child was not ended at the bound, took {elapsed:.1f}s"
    _assert_no_child_left()


def test_overrunning_child_gets_sigterm_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listening = tmp_path / "listening"
    monkeypatch.setenv(PID_FILE_VARIABLE, str(listening))
    # SIGTERM kills a child that has no handler yet, and that run proves nothing: only then a longer bound.
    for bound_s in (2.0, 5.0, 20.0):
        solver = OrToolsTourSolver(tour_child_main=_sigterm_recording_child, safety_bound_s=bound_s)

        assert solver.solve(ROUND_TRIP, ENOUGH_BUDGET) == TourTimedOut()
        if listening.exists():
            break

    assert listening.exists(), "the child never got to install its handler before the bound"
    assert listening.with_suffix(".received").exists(), "the child was ended without SIGTERM"
    _assert_no_child_left()


def test_child_ignoring_sigterm_gets_sigkill_after_the_grace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ignoring = tmp_path / "ignoring-sigterm"
    monkeypatch.setenv(PID_FILE_VARIABLE, str(ignoring))
    # SIGTERM kills a child that has not reached SIG_IGN yet, and that run proves nothing: only then a longer bound.
    for bound_s in (5.0, 10.0, 20.0):
        solver = OrToolsTourSolver(tour_child_main=_sigterm_ignoring_child, safety_bound_s=bound_s)

        started = time.monotonic()
        outcome = solver.solve(ROUND_TRIP, ENOUGH_BUDGET)
        elapsed = time.monotonic() - started

        assert outcome == TourTimedOut()
        if ignoring.exists():
            break

    assert ignoring.exists(), "the child never got to ignore SIGTERM before the bound"
    assert elapsed >= bound_s + SIGTERM_GRACE_S - 0.1, f"SIGKILL came before the grace ended, took {elapsed:.1f}s"
    assert elapsed < bound_s + SIGTERM_GRACE_S + SIGKILL_SLACK_S, f"the child outlived SIGKILL, took {elapsed:.1f}s"
    _assert_no_child_left()


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_until(condition: Callable[[], bool], timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


_SOLVING_PARENT = """
from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from tests.integration.adapters.solver import test_ortools_solve as here

if __name__ == "__main__":
    solver = OrToolsTourSolver(tour_child_main=here._real_child_reporting_its_pid)
    solver.solve(here._complete_model(60), 10**9)
"""


def test_child_dies_with_its_parent(tmp_path: Path) -> None:
    """The real solve holds the GIL in C++, so this also proves that the watchdog gets to run during the search."""
    pid_file = tmp_path / "child.pid"
    environ = {**os.environ, PID_FILE_VARIABLE: str(pid_file), "PYTHONPATH": str(REPO_ROOT)}
    script = tmp_path / "solving_parent.py"
    script.write_text(_SOLVING_PARENT)
    parent = subprocess.Popen([sys.executable, str(script)], cwd=REPO_ROOT, env=environ)
    child_pid = None
    try:
        assert _wait_until(pid_file.exists, 60.0), "the parent never reached a search with a solution"
        child_pid = int(pid_file.read_text())
        assert _is_alive(child_pid), "the solve ended before the parent was killed"

        parent.kill()
        parent.wait()

        gone = _wait_until(lambda: not _is_alive(child_pid), 15.0)  # its budget would keep it searching far longer
        assert gone, f"child {child_pid} still alive 15 s after its parent was killed"
    finally:
        parent.kill()
        parent.wait()
        if child_pid is not None and _is_alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)


@pytest.mark.skipif(sys.platform != "linux", reason="PR_SET_PDEATHSIG exists only on Linux")
def test_linux_child_asks_to_be_killed_with_its_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = tmp_path / "death-signal"
    monkeypatch.setenv(PID_FILE_VARIABLE, str(report))

    OrToolsTourSolver(tour_child_main=_child_reporting_its_death_signal).solve(ROUND_TRIP, ENOUGH_BUDGET)

    assert report.read_text() == str(int(signal.SIGKILL))


_CHECKED_SERVER = """
import sys

from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from overland_planner.bootstrap.app_factory import create_app
from overland_planner.domain.planning.solver_model_builder import TourModel


def ortools_loaded():
    return sorted(name for name in sys.modules if name == "ortools" or name.startswith("ortools."))


if __name__ == "__main__":
    print("after import:", ortools_loaded())
    create_app({"DATA_DIR": sys.argv[1]})  # default settings: the real solver, probed in its child
    print("after create_app:", ortools_loaded())
    model = TourModel(("s", "e"), 0, 1, ((None, 5), (None, None)))
    print("solved:", OrToolsTourSolver().solve(model, 10))
    print("after solve:", ortools_loaded())
"""


def test_importing_and_building_the_app_and_solving_leave_ortools_out(tmp_path: Path) -> None:
    script = tmp_path / "checked_server.py"
    script.write_text(_CHECKED_SERVER)

    with workspace_data_dir("integration") as data_dir:
        command = [sys.executable, str(script), str(data_dir)]
        result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=90)

    assert result.returncode == 0, result.stderr
    printed = [line for line in result.stdout.splitlines() if not line.startswith("{")]  # not the event log's lines
    assert printed == [
        "after import: []",
        "after create_app: []",
        "solved: TourFound(order=('s', 'e'), ending='budget')",
        "after solve: []",
    ]


def test_a_child_that_could_not_start_is_a_child_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Out of memory on the Pi, for example; only the start of the process is made to fail."""

    def out_of_memory(_child: BaseProcess) -> None:
        raise OSError(errno.ENOMEM, "Cannot allocate memory")

    monkeypatch.setattr(BaseProcess, "start", out_of_memory)

    assert OrToolsTourSolver().solve(ROUND_TRIP, ENOUGH_BUDGET) == TourOptimizerFailed(exit_code=None, signal=None)

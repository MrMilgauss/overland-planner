"""A tour solved by OR-Tools in a child process (ADR-014 budget, ADR-015 solver child, D122 reason codes, D200 bound).

Integration level: single examples verify wiring against real spawned children, real OR-Tools and real signals. Every
expected order comes from an enumeration of the model's tours, not from the solver. What each child observation means
lives in tests/unit/adapters/solver/test_tour_outcome.py.

The faulty child entry points are module-level so the spawn context can import them in the child.
"""

from __future__ import annotations

import itertools
import multiprocessing
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path

import pytest

from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from overland_planner.adapters.solver.tour_child import run_tour_child
from overland_planner.application.ports.tour_solver import (
    TourFound,
    TourNoRoute,
    TourOptimizerFailed,
    TourTimedOut,
)
from overland_planner.domain.planning.solver_model_builder import TourModel

pytestmark = pytest.mark.solver_child

REPO_ROOT = Path(__file__).resolve().parents[4]
PID_FILE_VARIABLE = "TOUR_CHILD_TEST_PID_FILE"
ENOUGH_BUDGET = 500
DEFAULT_BUDGET = 10_000
SIGTERM_GRACE_S = 2.0
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


def _sigterm_ignoring_child(_answer: Connection, _model: TourModel, _budget: int) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(60)


def _real_child_reporting_its_pid(answer: Connection, model: TourModel, budget: int) -> None:
    """The real solve, after importing OR-Tools, so the test can kill the parent while the solve is running."""
    import ortools.constraint_solver.pywrapcp  # noqa: F401

    Path(os.environ[PID_FILE_VARIABLE]).write_text(str(os.getpid()))
    run_tour_child(answer, model, budget)


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
    ],
    ids=["exit-code", "sigkill", "exception", "no-message", "garbled-message"],
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


def test_overrunning_child_is_killed() -> None:
    bound_s = 1.0
    solver = OrToolsTourSolver(tour_child_main=_hanging_child, safety_bound_s=bound_s)

    started = time.monotonic()
    outcome = solver.solve(ROUND_TRIP, ENOUGH_BUDGET)
    elapsed = time.monotonic() - started

    assert outcome == TourTimedOut()
    assert outcome.reason == "timeout"
    assert bound_s <= elapsed < bound_s + SIGTERM_GRACE_S, f"SIGTERM must end it at the bound, took {elapsed:.1f}s"
    _assert_no_child_left()


def test_child_ignoring_sigterm_gets_sigkill_after_the_grace() -> None:
    # Long enough for the child to import this module and ignore SIGTERM before the bound, even on a loaded machine.
    bound_s = 5.0
    solver = OrToolsTourSolver(tour_child_main=_sigterm_ignoring_child, safety_bound_s=bound_s)

    started = time.monotonic()
    outcome = solver.solve(ROUND_TRIP, ENOUGH_BUDGET)
    elapsed = time.monotonic() - started

    assert outcome == TourTimedOut()
    assert elapsed >= bound_s + SIGTERM_GRACE_S - 0.1, f"SIGKILL came before the grace ended, took {elapsed:.1f}s"
    assert elapsed < bound_s + SIGTERM_GRACE_S + 3.0, f"the child outlived SIGKILL, took {elapsed:.1f}s"
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
        assert _wait_until(pid_file.exists, 30.0), "the parent never reached a running solve child"
        assert _wait_until(lambda: pid_file.read_text() != "", 1.0)
        child_pid = int(pid_file.read_text())
        time.sleep(1.0)  # the model is built and the search under way
        assert _is_alive(child_pid), "the solve ended before the parent was killed"

        parent.kill()
        parent.wait()

        gone = _wait_until(lambda: not _is_alive(child_pid), 3.0)
        assert gone, f"child {child_pid} still alive 3 s after its parent was killed"
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
from overland_planner.bootstrap.app_factory import create_app  # noqa: F401
from overland_planner.domain.planning.solver_model_builder import TourModel


def ortools_loaded():
    return sorted(name for name in sys.modules if name == "ortools" or name.startswith("ortools."))


if __name__ == "__main__":
    print("after import:", ortools_loaded())
    model = TourModel(("s", "e"), 0, 1, ((None, 5), (None, None)))
    print("solved:", OrToolsTourSolver().solve(model, 10))
    print("after solve:", ortools_loaded())
"""


def test_importing_the_app_factory_leaves_ortools_out(tmp_path: Path) -> None:
    script = tmp_path / "checked_server.py"
    script.write_text(_CHECKED_SERVER)

    result = subprocess.run([sys.executable, str(script)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "after import: []",
        "solved: TourFound(order=('s', 'e'))",
        "after solve: []",
    ]

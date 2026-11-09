"""`TourSolver` doubles for the recorded waivers W1/W2 (docs/architecture/atdd-infrastructure-policy.md).

Passed as `ExternalPorts(tour_solver=...)`. `HoldingTourSolver` hands the same call to the real solver once it is let
go, and `UnavailableTourSolver` must never be asked to solve at all; both accept any `solve` arguments. Slice 02 adds
`RuleBreakingTourSolver` (W1: the one double that invents an order, a rule-breaking one) and
`InProcessOrToolsTourSolver` (not a waiver: the real solve, hosted in the test process for the layer 1-2 properties).
Slice 03 adds `ScriptedTourSolver` (W1: the production parent with a scripted child that sends incumbents, stays
silent, ends without a route, or is killed after an incumbent) and `FollowingClock` for the wall-clock limits.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import signal
import threading
import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from overland_planner.adapters.solver.ortools_tour_solver import (
    OrToolsTourSolver,
    TourChildObservation,
    incumbent_of,
    tour_outcome,
)
from overland_planner.adapters.solver.tour_child import FINAL, INCUMBENT, run_tour_child
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.tour_solver import (
    IncumbentObserver,
    TourFound,
    TourOutcome,
    ignore_incumbents,
)
from overland_planner.domain.planning.solver_model_builder import TourModel
from tests.common.fakes import FakeClock

MAX_HOLD_S = 60.0  # a plan job that blocks the request itself fails the scenario instead of hanging the suite


class SolveAbandonedError(RuntimeError):
    """The scenario ended while the solve was still held."""


class HoldingTourSolver:
    """Keeps a plan "still being worked out" until the test lets it go; healthy at start-up (waiver W1)."""

    def __init__(self, solver: Any = None, *, max_hold_s: float = MAX_HOLD_S) -> None:
        self._solver: Any = solver if solver is not None else OrToolsTourSolver()
        self.identity = f"holding:{self._solver.identity}"
        self._max_hold_s = max_hold_s
        self._asked = threading.Event()
        self._let_go = threading.Event()
        self._abandoned = False

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def solve(self, *args: Any, **kwargs: Any) -> Any:
        self._asked.set()
        self._let_go.wait(self._max_hold_s)
        if self._abandoned:
            raise SolveAbandonedError("the scenario ended while this solve was held")
        return self._solver.solve(*args, **kwargs)

    def wait_until_asked(self, timeout_s: float) -> bool:
        return self._asked.wait(timeout_s)

    def let_go(self) -> None:
        self._let_go.set()

    def abandon(self) -> None:
        self._abandoned = True
        self._let_go.set()


class UnavailableTourSolver:
    """An optimizer that could not start: the same probe outcome as a failed OR-Tools child (waiver W2)."""

    identity = "unavailable-tour-solver"

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="degraded-unhealthy", reason="optimizer_unavailable")

    def solve(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("plans must be refused before they reach an optimizer that could not start")


REVERSED = "reversed:"  # the name a rule-breaking order gives a track driven exit -> entry (no such node exists)


class RuleBreakingTourSolver:
    """Plans for real until armed, then proposes an order that drives one track from its exit to its entry (W1).

    The port's order names item ids and a track has one node with no reversed variant (HC-1, brief section 8), so a
    reversed traversal can only be proposed as a node the model never offered: `REVERSED + track id` in the track's
    place. The guard must refuse it before any stop is made of it.
    """

    def __init__(self, solver: Any = None) -> None:
        self._solver: Any = solver if solver is not None else OrToolsTourSolver()
        self.identity = f"rule-breaking:{self._solver.identity}"
        self._reversed_track_id: str | None = None

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def drive_reversed(self, track_id: str) -> None:
        self._reversed_track_id = track_id

    def solve(self, model: TourModel, budget: int, on_incumbent: IncumbentObserver = ignore_incumbents) -> TourOutcome:
        if self._reversed_track_id is None:
            outcome: TourOutcome = self._solver.solve(model, budget, on_incumbent)
            return outcome
        track_id = self._reversed_track_id
        assert track_id in model.node_item_ids, f"the track {track_id} is not in the plan"
        return TourFound(order=tuple(REVERSED + node if node == track_id else node for node in model.node_item_ids))


class _CapturedAnswer:
    """The child's end of the pipe, kept in-process: it keeps every message the solve sends, in order."""

    def __init__(self) -> None:
        self.messages: list[Any] = []

    def send(self, message: Any) -> None:
        self.messages.append(message)

    def close(self) -> None:
        pass


class InProcessOrToolsTourSolver:
    """The real OR-Tools solve of the solver child (same model, first-solution strategy, metaheuristic and count-based
    budget, `tour_child.run_tour_child`), run in the test process instead of a spawned child, and read back by the
    adapter's own `tour_outcome`. For the layer 1-2 properties only (D192: hosting is DELIVER's call); every other
    acceptance scenario keeps the production `OrToolsTourSolver` child."""

    identity = f"in-process:{OrToolsTourSolver.identity}"

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def solve(self, model: TourModel, budget: int, on_incumbent: IncumbentObserver = ignore_incumbents) -> TourOutcome:
        answer = _CapturedAnswer()
        run_tour_child(answer, model, budget)  # type: ignore[arg-type]
        for message in answer.messages:  # after the search, not as found: only the hosting differs from the child
            incumbent = incumbent_of(message, model)
            if incumbent is not None:
                on_incumbent(incumbent)
        return tour_outcome(TourChildObservation(exit_code=0, messages=tuple(answer.messages)), model)


# ---------------------------------------------------------------------------------------------------- slice 03 (W1)
SCRIPTED_CHILD_LIFE_S = 60.0  # a scripted child that "keeps searching" ends itself after this, so none outlives a test
SCRIPTS = ("improving", "silent", "no_route", "finish")


def scripted_tour_child(
    answer: Connection, model: TourModel, budget: int, *, script: str, record: str, life_s: float
) -> None:
    """A solve child that speaks the child protocol without OR-Tools (waiver W1), started by the real parent.

    - `improving`: sends two valid incumbents (the second better), then keeps "searching" without a final message;
    - `silent`: never finds a valid route and never sends anything;
    - `no_route`: ends its search at once with `(FINAL, None)`;
    - `finish`: sends a valid incumbent and its final order at once.
    Each child appends its pid and the item ids of every incumbent it sent to `record` (JSON lines), so the scenario
    knows the best route so far and which process to end."""
    _append(record, {"pid": os.getpid(), "script": script})
    middle = [node for node in range(len(model.node_item_ids)) if node not in (model.start_node, model.end_node)]
    worse = (model.start_node, *reversed(middle), model.end_node)
    best = (model.start_node, *middle, model.end_node)
    if script == "no_route":
        answer.send((FINAL, None))
        answer.close()
        return
    if script in ("improving", "finish"):
        for objective, order in ((2_000.0, worse), (1_000.0, best)):
            answer.send((INCUMBENT, order, objective))
            _append(record, {"incumbent": [model.node_item_ids[node] for node in order], "objective": objective})
        if script == "finish":
            answer.send((FINAL, best))
            answer.close()
            return
    time.sleep(life_s)
    os._exit(0)  # pipe EOF without a final message


def _append(record: str, entry: dict[str, Any]) -> None:
    with open(record, "a", encoding="utf-8") as sink:
        sink.write(json.dumps(entry) + "\n")


class ScriptedTourSolver(OrToolsTourSolver):
    """The production solver adapter (parent side: spawn, pipe, limits, kill) with a scripted child (waiver W1).

    `scripts` names the child of each successive solve; the last one repeats. The start-up probe answers ok without
    a probe child. `incumbents()` lists what the children sent (item ids), `kill_child()` ends the running child with
    SIGKILL ("the optimizer stops abnormally"), `abandon()` ends every child still alive when the scenario ends."""

    def __init__(self, scripts: Sequence[str], record_dir: Path, *, life_s: float = SCRIPTED_CHILD_LIFE_S) -> None:
        assert scripts and set(scripts) <= set(SCRIPTS), f"unknown scripts {scripts}"
        super().__init__()
        self.identity = "scripted-tour-solver:" + "+".join(scripts)
        self._scripts = list(scripts)
        self._life_s = life_s
        record_dir.mkdir(parents=True, exist_ok=True)
        self._record = record_dir / "scripted-children.jsonl"
        self.calls = 0

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def solve(self, *args: Any, **kwargs: Any) -> Any:
        """Same arguments as the production adapter, whatever slice 03 adds to `solve` (limits, Stop)."""
        script = self._scripts[min(self.calls, len(self._scripts) - 1)]
        self.calls += 1
        self._tour_child_main = functools.partial(
            scripted_tour_child, script=script, record=str(self._record), life_s=self._life_s
        )
        return super().solve(*args, **kwargs)

    def _entries(self) -> list[dict[str, Any]]:
        if not self._record.exists():
            return []
        return [json.loads(line) for line in self._record.read_text(encoding="utf-8").splitlines() if line]

    def incumbents(self) -> list[list[str]]:
        return [entry["incumbent"] for entry in self._entries() if "incumbent" in entry]

    def child_pids(self) -> list[int]:
        return [int(entry["pid"]) for entry in self._entries() if "pid" in entry]

    def kill_child(self) -> None:
        pids = self.child_pids()
        assert pids, "no optimizer child was started"
        os.kill(pids[-1], signal.SIGKILL)

    def abandon(self) -> None:
        for pid in self.child_pids():
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)


class FollowingClock(FakeClock):
    """`Clock` double that follows real time from the fixed start (the limits are wall-clock limits, ADR-014)."""

    def __init__(self) -> None:
        super().__init__()
        self._started_at = time.monotonic()

    def now(self) -> datetime:
        return super().now() + timedelta(seconds=time.monotonic() - self._started_at)

    def monotonic(self) -> float:
        return time.monotonic()

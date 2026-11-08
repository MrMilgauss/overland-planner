"""`TourSolver` doubles for the recorded waivers W1/W2 (docs/architecture/atdd-infrastructure-policy.md).

Passed as `ExternalPorts(tour_solver=...)`. `HoldingTourSolver` hands the same call to the real solver once it is let
go, and `UnavailableTourSolver` must never be asked to solve at all; both accept any `solve` arguments. Slice 02 adds
`RuleBreakingTourSolver` (W1: the one double that invents an order, a rule-breaking one) and
`InProcessOrToolsTourSolver` (not a waiver: the real solve, hosted in the test process for the layer 1-2 properties).
"""

from __future__ import annotations

import threading
from typing import Any

from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver, TourChildObservation, tour_outcome
from overland_planner.adapters.solver.tour_child import run_tour_child
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.tour_solver import TourFound, TourOutcome
from overland_planner.domain.planning.solver_model_builder import TourModel

MAX_HOLD_S = 60.0  # a plan job that blocks the request itself fails the scenario instead of hanging the suite


class SolveAbandonedError(RuntimeError):
    """The scenario ended while the solve was still held."""


class HoldingTourSolver:
    """Keeps a plan "still being worked out" until the test lets it go; healthy at start-up (waiver W1)."""

    def __init__(self, solver: Any = None, *, max_hold_s: float = MAX_HOLD_S) -> None:
        self._solver: Any = solver if solver is not None else OrToolsTourSolver()
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
        self._reversed_track_id: str | None = None

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def drive_reversed(self, track_id: str) -> None:
        self._reversed_track_id = track_id

    def solve(self, model: TourModel, budget: int) -> TourOutcome:
        if self._reversed_track_id is None:
            outcome: TourOutcome = self._solver.solve(model, budget)
            return outcome
        track_id = self._reversed_track_id
        assert track_id in model.node_item_ids, f"the track {track_id} is not in the plan"
        return TourFound(order=tuple(REVERSED + node if node == track_id else node for node in model.node_item_ids))


class _CapturedAnswer:
    """The child's end of the pipe, kept in-process: it keeps the one message the solve sends."""

    def __init__(self) -> None:
        self.message: Any = None

    def send(self, message: Any) -> None:
        self.message = message

    def close(self) -> None:
        pass


class InProcessOrToolsTourSolver:
    """The real OR-Tools solve of the solver child (same model, first-solution strategy, metaheuristic and count-based
    budget, `tour_child.run_tour_child`), run in the test process instead of a spawned child, and read back by the
    adapter's own `tour_outcome`. For the layer 1-2 properties only (D192: hosting is DELIVER's call); every other
    acceptance scenario keeps the production `OrToolsTourSolver` child."""

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def solve(self, model: TourModel, budget: int) -> TourOutcome:
        answer = _CapturedAnswer()
        run_tour_child(answer, model, budget)  # type: ignore[arg-type]
        return tour_outcome(TourChildObservation(exit_code=0, message=answer.message, overran=False), model)

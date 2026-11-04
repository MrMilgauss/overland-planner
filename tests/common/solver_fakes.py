"""`TourSolver` doubles for the recorded waivers W1/W2 (docs/architecture/atdd-infrastructure-policy.md).

Passed as `ExternalPorts(tour_solver=...)`. Neither invents a solver result: `HoldingTourSolver` hands the same call to
the real solver once it is let go, and `UnavailableTourSolver` must never be asked to solve at all. Both accept any
`solve` arguments on purpose: the port declares only `probe()` until DELIVER of slice 01b adds
`solve(model, budget, limits, stop_signal)` (brief §6).
"""

from __future__ import annotations

import threading
from typing import Any

from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from overland_planner.application.ports.probe import ProbeResult

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

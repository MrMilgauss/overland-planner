"""`TourSolver` adapter backed by OR-Tools, run in a short-lived child process (ADR-015, ADR-011 Amendment 1).

Slice 00a: only the start-up probe. The child (spawn context, so no state is inherited from the server) imports
OR-Tools, solves the fixed probe instance twice and sends both answers through a one-way pipe; OR-Tools is never
imported in the server process (idle-RAM guardrail G1). The parent waits at most `timeout_s`, then kills the child,
so a hung or orphan-prone child cannot outlive the probe. PDEATHSIG and the pipe-EOF watchdog of ADR-015 arrive with
the long-running solve children (slice 01b); a probe child is always reaped here.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

from overland_planner.adapters.solver.probe_instance import (
    DEPOT,
    FORBIDDEN_ARC,
    NODE_COUNT,
    ProbeObservation,
    Solve,
    arc_cost,
    probe_verdict,
)
from overland_planner.application.ports.probe import ProbeResult

PROBE_TIMEOUT_S = 30.0  # bounds a hung child; a cold first import of OR-Tools took over 10 s once on the Mac
_PROBE_SOLUTION_LIMIT = 100
_REAP_TIMEOUT_S = 2.0


def _solve_probe_instance() -> Solve:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    manager = pywrapcp.RoutingIndexManager(NODE_COUNT, 1, DEPOT)
    routing = pywrapcp.RoutingModel(manager)

    def transit(from_index: int, to_index: int) -> int:
        return arc_cost(manager.IndexToNode(from_index), manager.IndexToNode(to_index))

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(transit))
    origin, destination = FORBIDDEN_ARC
    routing.NextVar(manager.NodeToIndex(origin)).RemoveValue(manager.NodeToIndex(destination))
    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    parameters.solution_limit = _PROBE_SOLUTION_LIMIT
    solution = routing.SolveWithParameters(parameters)
    order = []
    index = solution.Value(routing.NextVar(routing.Start(0)))
    while not routing.IsEnd(index):
        order.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))
    return tuple(order), int(solution.ObjectiveValue())


def solve_probe_instance_twice(answer: Connection) -> None:
    """Child entry point: two independent solves of the probe instance, sent back as one message."""
    answer.send((_solve_probe_instance(), _solve_probe_instance()))
    answer.close()


class OrToolsTourSolver:
    def __init__(
        self,
        *,
        child_main: Callable[[Connection], None] = solve_probe_instance_twice,
        timeout_s: float = PROBE_TIMEOUT_S,
    ) -> None:
        self._child_main = child_main
        self._timeout_s = timeout_s

    def probe(self) -> ProbeResult:
        return probe_verdict(self._observe_probe_child())

    def _observe_probe_child(self) -> ProbeObservation:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        child = context.Process(target=self._child_main, args=(sender,), name="tour-solver-probe", daemon=True)
        child.start()
        sender.close()
        answer: Any = None
        try:
            answer = _receive(receiver, self._timeout_s)
        finally:
            receiver.close()
            child.join(_REAP_TIMEOUT_S if answer is not None else 0)
            if child.is_alive():
                child.kill()
                child.join()
        return ProbeObservation(exit_code=child.exitcode, solves=_solves(answer))


def _receive(receiver: Connection, timeout_s: float) -> Any:
    """The child's message, or None when it sent nothing in time (hang) or closed the pipe without sending (crash)."""
    try:
        return receiver.recv() if receiver.poll(timeout_s) else None
    except (EOFError, OSError):
        return None


def _solves(answer: Any) -> tuple[Solve, ...]:
    return tuple(answer) if isinstance(answer, tuple) else ()

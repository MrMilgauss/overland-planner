"""`TourSolver` adapter backed by OR-Tools, run in a short-lived child process (ADR-015, ADR-011 Amendment 1).

Every child (spawn context, so no state is inherited from the server) imports OR-Tools itself; OR-Tools is never
imported in the server process (idle-RAM guardrail G1).

The probe child solves the fixed probe instance twice and sends both answers through a one-way pipe. The parent waits at
most `timeout_s`, then kills it.

A solve spawns one child (`tour_child`) that sends its final message and exits; `tour_outcome` says what its end means.
It dies with its parent through PR_SET_PDEATHSIG (Linux) and a pipe-EOF watchdog (also macOS). Past `safety_bound_s`
the parent ends it with SIGTERM, then SIGKILL after 2 s: without the bound a hung child would hold the project in 409
until a restart. The bound is the FEASIBILITY_LIMIT_S default, not the configurable limits of slice 03, and the normal
stop is the budget, never the clock.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
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
from overland_planner.adapters.solver.tour_child import (
    FINAL,
    TourChildMain,
    first_solution_search_parameters,
    run_tour_child,
    tour_child_entry,
)
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.tour_solver import (
    TourFound,
    TourNoRoute,
    TourOptimizerFailed,
    TourOutcome,
    TourTimedOut,
)
from overland_planner.domain.planning.solver_model_builder import TourModel

PROBE_TIMEOUT_S = 30.0  # bounds a hung child; a cold first import of OR-Tools took over 10 s once on the Mac
_PROBE_SOLUTION_LIMIT = 100
_REAP_TIMEOUT_S = 2.0
SOLVE_SAFETY_BOUND_S = 600.0  # the FEASIBILITY_LIMIT_S default (D200)
_SIGTERM_GRACE_S = 2.0


def _solve_probe_instance() -> Solve:
    from ortools.constraint_solver import pywrapcp

    manager = pywrapcp.RoutingIndexManager(NODE_COUNT, 1, DEPOT)
    routing = pywrapcp.RoutingModel(manager)

    def transit(from_index: int, to_index: int) -> int:
        return arc_cost(manager.IndexToNode(from_index), manager.IndexToNode(to_index))

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(transit))
    origin, destination = FORBIDDEN_ARC
    routing.NextVar(manager.NodeToIndex(origin)).RemoveValue(manager.NodeToIndex(destination))
    solution = routing.SolveWithParameters(first_solution_search_parameters(_PROBE_SOLUTION_LIMIT))
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
        tour_child_main: TourChildMain = run_tour_child,
        safety_bound_s: float = SOLVE_SAFETY_BOUND_S,
    ) -> None:
        self._child_main = child_main
        self._timeout_s = timeout_s
        self._tour_child_main = tour_child_main
        self._safety_bound_s = safety_bound_s

    def probe(self) -> ProbeResult:
        return probe_verdict(self._observe_probe_child())

    def solve(self, model: TourModel, budget: int) -> TourOutcome:
        return tour_outcome(self._observe_tour_child(model, budget), model)

    def _observe_tour_child(self, model: TourModel, budget: int) -> TourChildObservation:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        arguments = (self._tour_child_main, sender, model, budget)
        child = context.Process(target=tour_child_entry, args=arguments, name="tour-solver-solve", daemon=True)
        child.start()
        sender.close()
        message: Any = None
        overran = False
        try:
            overran = not receiver.poll(self._safety_bound_s)
            if not overran:
                message = _read_message(receiver)
                child.join(_REAP_TIMEOUT_S)
        finally:
            receiver.close()
            _end_if_running(child)
        return TourChildObservation(exit_code=child.exitcode, message=message, overran=overran)

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


@dataclass(frozen=True)
class TourChildObservation:
    """What the parent saw of a solve child."""

    exit_code: int | None
    message: Any
    overran: bool


def tour_outcome(observation: TourChildObservation, model: TourModel) -> TourOutcome:
    if observation.overran:
        return TourTimedOut()
    message = observation.message
    if observation.exit_code != 0 or not _is_final(message):
        return _failed(observation.exit_code)
    nodes = message[1]
    if nodes is None:
        return TourNoRoute()
    if not _is_complete_tour(nodes, model):
        return _failed(observation.exit_code)
    return TourFound(order=tuple(model.node_item_ids[node] for node in nodes))


def _is_final(message: Any) -> bool:
    return isinstance(message, tuple) and len(message) == 2 and message[0] == FINAL


def _is_complete_tour(nodes: Any, model: TourModel) -> bool:
    if not isinstance(nodes, tuple) or not all(type(node) is int for node in nodes):
        return False
    every_node_once = sorted(nodes) == list(range(len(model.node_item_ids)))
    return every_node_once and nodes[0] == model.start_node and nodes[-1] == model.end_node


def _failed(exit_code: int | None) -> TourOptimizerFailed:
    """multiprocessing reports a child ended by signal N as exit code -N."""
    if exit_code is not None and exit_code < 0:
        return TourOptimizerFailed(exit_code=None, signal=-exit_code)
    return TourOptimizerFailed(exit_code=exit_code, signal=None)


def _read_message(receiver: Connection) -> Any:
    """The child's message, or None when it closed the pipe without one or sent something unreadable.

    What a broken child wrote can fail unpickling in many ways; each one ends as `optimizer_failed`, which reports it.
    """
    try:
        return receiver.recv()
    except Exception:
        return None


def _end_if_running(child: BaseProcess) -> None:
    if not child.is_alive():
        return
    child.terminate()
    child.join(_SIGTERM_GRACE_S)
    if child.is_alive():
        child.kill()
        child.join()


def _receive(receiver: Connection, timeout_s: float) -> Any:
    """The child's message, or None when it sent nothing in time (hang) or closed the pipe without sending (crash)."""
    try:
        return receiver.recv() if receiver.poll(timeout_s) else None
    except (EOFError, OSError):
        return None


def _solves(answer: Any) -> tuple[Solve, ...]:
    return tuple(answer) if isinstance(answer, tuple) else ()

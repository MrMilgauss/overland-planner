"""The solve child's side of the pipe (ADR-014 budget, ADR-015 solver child). OR-Tools is imported only in functions.

The server imports this module, and importing it must leave OR-Tools out (idle-RAM guardrail G1); the child gets the
import the first time it builds a model.

The child sends one message and exits: `(FINAL, node_order)` with Start first and End last, or `(FINAL, None)` when the
solver finds no route. Slice 03 adds incumbents.

A child dies with its parent in two ways (ADR-015, spike check j): on Linux `PR_SET_PDEATHSIG`, and everywhere a daemon
thread that waits for end-of-file on multiprocessing's parent sentinel pipe. PDEATHSIG fires when the thread that
spawned the child ends; `OrToolsTourSolver.solve` blocks that thread for the child's whole life.
"""

from __future__ import annotations

import ctypes
import multiprocessing
import os
import signal
import sys
import threading
from collections.abc import Callable
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Any

from overland_planner.domain.planning.solver_model_builder import TourModel

TourChildMain = Callable[[Connection, TourModel, int], None]

FINAL = "final"
_NO_ARC_COST = 0  # never travelled: every missing arc is removed from the model
_PR_SET_PDEATHSIG = 1
_EXIT_PARENT_GONE = 70


def first_solution_search_parameters(solution_limit: int) -> Any:
    """The search settings shared with the probe: the first-solution strategy and the count-based stop (ADR-014)."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    parameters.solution_limit = solution_limit
    return parameters


def tour_child_entry(main: TourChildMain, answer: Connection, model: TourModel, budget: int) -> None:
    """Spawn target: every solve child, real or scripted, is tied to its parent before it does anything else."""
    _die_with_parent()
    main(answer, model, budget)


def run_tour_child(answer: Connection, model: TourModel, budget: int) -> None:
    answer.send((FINAL, _solve(model, budget)))
    answer.close()


def _die_with_parent() -> None:
    if sys.platform == "linux":
        ctypes.CDLL(None).prctl(_PR_SET_PDEATHSIG, int(signal.SIGKILL))
    parent = multiprocessing.parent_process()
    if parent is not None:
        threading.Thread(target=_exit_once_gone, args=(parent,), name="parent-watchdog", daemon=True).start()


def _exit_once_gone(parent: BaseProcess) -> None:
    parent.join()
    os._exit(_EXIT_PARENT_GONE)


def _solve(model: TourModel, budget: int) -> tuple[int, ...] | None:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    manager = pywrapcp.RoutingIndexManager(len(model.arc_m), 1, [model.start_node], [model.end_node])
    routing = pywrapcp.RoutingModel(manager)
    costs = [[_NO_ARC_COST if cost is None else cost for cost in row] for row in model.arc_m]
    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitMatrix(costs))
    _remove_missing_arcs(routing, manager, model)

    # The search holds the GIL in C++ and gives it up only to call Python, so without this callback the watchdog never
    # runs during a solve (checked on OR-Tools 9.15). Slice 03 sends the incumbents from here.
    def hand_over_the_gil() -> None:
        pass

    routing.AddAtSolutionCallback(hand_over_the_gil)
    parameters = first_solution_search_parameters(budget)
    parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    solution = routing.SolveWithParameters(parameters)
    return None if solution is None else _node_order(routing, manager, solution)


def _remove_missing_arcs(routing: Any, manager: Any, model: TourModel) -> None:
    """The routing model itself gives Start no arc in and End no arc out; only the other arcs need removing."""
    nodes = range(len(model.arc_m))
    origins = [node for node in nodes if node != model.end_node]
    destinations = [node for node in nodes if node != model.start_node]
    for origin in origins:
        for destination in destinations:
            if origin != destination and model.arc_m[origin][destination] is None:
                target = routing.End(0) if destination == model.end_node else manager.NodeToIndex(destination)
                routing.NextVar(manager.NodeToIndex(origin)).RemoveValue(target)


def _node_order(routing: Any, manager: Any, solution: Any) -> tuple[int, ...]:
    order = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        order.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))
    return (*order, manager.IndexToNode(index))

"""`TourSolver` adapter backed by OR-Tools, run in a short-lived child process (ADR-015, ADR-011 Amendment 1).

Every child (spawn context, so no state is inherited from the server) imports OR-Tools itself; OR-Tools is never
imported in the server process (idle-RAM guardrail G1).

The probe child solves the fixed probe instance twice and sends both answers through a one-way pipe. The parent waits at
most `timeout_s`, then kills it.

A solve spawns one child (`tour_child`) that streams its incumbents, sends its final message and exits. The parent reads
the pipe in the thread that spawned the child for the child's whole life (PR_SET_PDEATHSIG, `tour_child`), hands each
valid incumbent (`incumbent_of`) to the solve's observer as it arrives, and stops reading at the final or the pipe's
end; a message that is not a complete tour from Start to End is ignored. `tour_outcome` says what the messages and the
end mean (ADR-015's table): the final order when the child ended normally, else the last valid incumbent labelled
`optimizer_failed`, else Failed with the exit code or signal. A child still running when the reap wait after its final
ends (interpreter teardown can be slow on a loaded Pi) is ended like any other, and its final counts: the exit code
then only shows the parent's signal.

The child dies with its parent through PR_SET_PDEATHSIG (Linux) and a pipe-EOF watchdog (also macOS). No child waits
without a bound (D200): the parent reads in short waits against the solve's deadlines on the `Clock` port
(`read_tour_child`), never past the one that applies: the feasibility deadline until a valid incumbent arrived, then the
optimisation deadline. At that deadline it ends the child with SIGTERM, then SIGKILL after 2 s: the last incumbent
labelled `time_limit`, or Failed `timeout` without one (a hung child too). The budget ends a search that is quicker.
Stop ends it the same way: the parent checks the solve's stop signal between those short waits, so a Stop ends even a
child deaf to SIGTERM within a wait step and the grace: the last incumbent labelled `stopped`, or Failed `stopped`.
`SOLVER_IDENTITY` is the solver's `identity`, which the composition root hands to the fingerprint memo.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib.metadata import version
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
    INCUMBENT,
    TourChildMain,
    first_solution_search_parameters,
    run_tour_child,
    tour_child_entry,
)
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.tour_solver import (
    NEVER_STOPPED,
    Incumbent,
    IncumbentObserver,
    SolveDeadlines,
    StopSignal,
    TourFound,
    TourNoRoute,
    TourOptimizerFailed,
    TourOutcome,
    TourStopped,
    TourTimedOut,
    ignore_incumbents,
)
from overland_planner.domain.planning.run_messages import NotFullyOptimised
from overland_planner.domain.planning.solver_model_builder import TourModel

PROBE_TIMEOUT_S = 30.0  # bounds a hung child; a cold first import of OR-Tools took over 10 s once on the Mac
_PROBE_SOLUTION_LIMIT = 100
_REAP_TIMEOUT_S = 2.0
_SIGTERM_GRACE_S = 2.0
_WAIT_STEP_S = 0.25  # the longest wait on the pipe before the deadlines are checked again on the Clock port
# What makes this solver's orders what they are, for the fingerprint memo (ADR-014 sections 3 and 5): the installed
# OR-Tools release, read from its metadata without importing it (G1), and the search `tour_child` runs.
SOLVER_IDENTITY = f"ortools=={version('ortools')};PATH_CHEAPEST_ARC;GUIDED_LOCAL_SEARCH"


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
    identity = SOLVER_IDENTITY

    def __init__(
        self,
        *,
        child_main: Callable[[Connection], None] = solve_probe_instance_twice,
        timeout_s: float = PROBE_TIMEOUT_S,
        tour_child_main: TourChildMain = run_tour_child,
    ) -> None:
        self._child_main = child_main
        self._timeout_s = timeout_s
        self._tour_child_main = tour_child_main

    def probe(self) -> ProbeResult:
        return probe_verdict(self._observe_probe_child())

    def solve(
        self,
        model: TourModel,
        budget: int,
        on_incumbent: IncumbentObserver = ignore_incumbents,
        *,
        deadlines: SolveDeadlines,
        stop: StopSignal = NEVER_STOPPED,
    ) -> TourOutcome:
        return tour_outcome(self._observe_tour_child(model, budget, on_incumbent, _Bounds(deadlines, stop)), model)

    def _observe_tour_child(
        self, model: TourModel, budget: int, on_incumbent: IncumbentObserver, bounds: _Bounds
    ) -> TourChildObservation:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        arguments = (self._tour_child_main, sender, model, budget)
        child = context.Process(target=tour_child_entry, args=arguments, name="tour-solver-solve", daemon=True)
        try:
            child.start()
        except OSError:  # for example out of memory on the Pi: a process that could not start is a child failure
            receiver.close()
            sender.close()
            return TourChildObservation(exit_code=None)
        sender.close()
        outlived_reap_wait = False
        try:
            reading = read_tour_child(receiver, bounds.deadlines, model, on_incumbent, bounds.stop)
            if not (reading.overran or reading.stopped):
                child.join(_REAP_TIMEOUT_S)
                outlived_reap_wait = child.is_alive()
        finally:
            receiver.close()
            _end_if_running(child)
        return TourChildObservation(
            child.exitcode, reading.messages, reading.overran, outlived_reap_wait, stopped=reading.stopped
        )

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
class _Bounds:
    """What ends a solve before its budget: its deadlines and its stop signal."""

    deadlines: SolveDeadlines
    stop: StopSignal


@dataclass(frozen=True)
class TourChildObservation:
    """What the parent saw of a solve child: its messages in order, up to its final or the pipe's end (an unreadable
    message ends the reading); `overran` when the deadline that applies came first, `stopped` when Stop did.
    `outlived_reap_wait` is read before the parent ends the child."""

    exit_code: int | None
    messages: tuple[Any, ...] = ()
    overran: bool = False
    outlived_reap_wait: bool = False
    stopped: bool = False


def tour_outcome(observation: TourChildObservation, model: TourModel) -> TourOutcome:
    """ADR-015's table of endings: budget end -> the final order; an abnormal end -> the last valid incumbent labelled
    `optimizer_failed`, or Failed without one; a final without an order -> no route; the deadline that applies ->
    the last valid incumbent labelled `time_limit`, or Failed `timeout` without one; Stop -> the last valid incumbent
    labelled `stopped`, or Failed `stopped` without one.
    """
    incumbents = [found for message in observation.messages if (found := incumbent_of(message, model)) is not None]
    if observation.stopped:
        return _last_incumbent(incumbents, "stopped") or TourStopped()
    if observation.overran:
        return _last_incumbent(incumbents, "time_limit") or TourTimedOut()
    ended_normally = observation.exit_code == 0 or observation.outlived_reap_wait
    final = next((message for message in observation.messages if _is_final(message)), None)
    if ended_normally and final is not None:
        if final[1] is None:
            return TourNoRoute()
        if _is_complete_tour(final[1], model):
            return TourFound(order=_item_ids(final[1], model))
    return _last_incumbent(incumbents, "optimizer_failed") or _failed(observation.exit_code)


def _last_incumbent(incumbents: Sequence[Incumbent], ending: NotFullyOptimised) -> TourFound | None:
    """The last valid incumbent labelled with how its search ended, `None` without one."""
    return TourFound(order=incumbents[-1].order, ending=ending) if incumbents else None


def incumbent_of(message: Any, model: TourModel) -> Incumbent | None:
    """The incumbent a message carries, or `None` when it is no `(INCUMBENT, complete tour, objective)`."""
    if not (isinstance(message, tuple) and len(message) == 3 and message[0] == INCUMBENT):
        return None
    _, nodes, objective = message
    if type(objective) not in (int, float) or not _is_complete_tour(nodes, model):
        return None
    return Incumbent(order=_item_ids(nodes, model), objective=objective)


@dataclass(frozen=True)
class ChildReading:
    """The messages the parent read from a solve child, in order, and whether the deadline that applies or Stop came
    first."""

    messages: tuple[Any, ...] = ()
    overran: bool = False
    stopped: bool = False


def read_tour_child(
    receiver: Connection,
    deadlines: SolveDeadlines,
    model: TourModel,
    on_incumbent: IncumbentObserver,
    stop: StopSignal = NEVER_STOPPED,
) -> ChildReading:
    """Reads until the final, the pipe's end or an unreadable message, handing each valid incumbent to `on_incumbent`;
    overran when the deadline that applies passed first: the feasibility one until a valid incumbent arrived, then the
    optimisation one; stopped when `stop` was set first. It waits at most `_WAIT_STEP_S` at a time and never past that
    deadline, and checks `stop` before each wait."""
    messages: list[Any] = []
    found = False
    while (remaining_s := deadlines.remaining_s(found=found)) > 0:
        if stop.is_set():
            return ChildReading(tuple(messages), stopped=True)
        if not receiver.poll(min(remaining_s, _WAIT_STEP_S)):
            continue
        message = _read_message(receiver)
        if message is _UNREADABLE:
            return ChildReading(tuple(messages))
        messages.append(message)
        incumbent = incumbent_of(message, model)
        if incumbent is not None:
            found = True
            on_incumbent(incumbent)
        if _is_final(message):
            return ChildReading(tuple(messages))
    return ChildReading(tuple(messages), overran=True)


def _is_final(message: Any) -> bool:
    return isinstance(message, tuple) and len(message) == 2 and message[0] == FINAL


def _item_ids(nodes: tuple[int, ...], model: TourModel) -> tuple[str, ...]:
    return tuple(model.node_item_ids[node] for node in nodes)


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


_UNREADABLE = object()


def _read_message(receiver: Connection) -> Any:
    """The child's next message, or `_UNREADABLE` at the pipe's end or for something that cannot be read.

    What a broken child wrote can fail unpickling in many ways; each one ends the reading, and the child's end decides.
    """
    try:
        return receiver.recv()
    except Exception:
        return _UNREADABLE


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

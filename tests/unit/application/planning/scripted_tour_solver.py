"""`TourSolver` double for unit and adapter wiring tests: it answers with a scripted outcome, in-process and at once.

Mutation runs select unit and integration tests without `solver_child`, so job states are driven by this script and not
by OR-Tools (the waivers W1/W2 stay acceptance-only). The script is a `TourOutcome`, an exception to raise, or `None`
for the tour that visits the model's nodes in order. Like the real adapter it refuses a model without nodes or a budget
that is not positive. Before it ends it streams its scripted `incumbents` to the job's observer, the fake clock moved
on `incumbent_every_s` before each, as the solver child does (ADR-015, brief section 6). It keeps the deadlines each
solve was handed (`deadlines`; `None` for a caller that hands none) and refuses an optimisation deadline before the
feasibility one, which the real adapter could not honour. It keeps the stop signal each solve was handed (`stops`) and,
held at its gate, ends as the real adapter ends a stopped solve once that signal is set (brief section 6, ADR-015): the
last incumbent labelled `stopped`, or Failed `stopped` without one.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.tour_solver import (
    Incumbent,
    IncumbentObserver,
    SolveDeadlines,
    StopSignal,
    TourFound,
    TourOutcome,
    TourStopped,
    ignore_incumbents,
)
from overland_planner.domain.planning.solver_model_builder import TourModel
from tests.common.fakes import FakeClock
from tests.unit.application.planning.planning_doubles import Gate

Script = TourOutcome | BaseException | None
SCRIPTED_IDENTITY = "scripted-tour-solver"


class ScriptedTourSolver:
    def __init__(
        self,
        script: Script = None,
        *,
        gate: Gate | None = None,
        identity: str = SCRIPTED_IDENTITY,
        incumbents: Sequence[Incumbent] = (),
        clock: FakeClock | None = None,
        incumbent_every_s: float = 0.0,
    ) -> None:
        self.identity = identity
        self._script = script
        self._incumbents = tuple(incumbents)
        self._clock = clock
        self._every_s = incumbent_every_s
        self.gate = gate or Gate()
        self.models: list[TourModel] = []
        self.budgets: list[int] = []
        self.deadlines: list[SolveDeadlines | None] = []
        self.stops: list[StopSignal | None] = []
        self.threads: list[threading.Thread] = []

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def solve(
        self,
        model: TourModel,
        budget: int,
        on_incumbent: IncumbentObserver = ignore_incumbents,
        *,
        deadlines: SolveDeadlines | None = None,
        stop: StopSignal | None = None,
    ) -> TourOutcome:
        assert model.node_item_ids, "a model has at least the Start and End nodes"
        assert budget > 0, "the budget must be positive"
        assert deadlines is None or deadlines.feasibility_s <= deadlines.optimisation_s, "deadlines out of order"
        self.deadlines.append(deadlines)
        self.stops.append(stop)
        self.models.append(model)
        self.budgets.append(budget)
        self.threads.append(threading.current_thread())
        for incumbent in self._incumbents:
            if self._clock is not None:
                self._clock.advance(self._every_s)
            on_incumbent(incumbent)
        self.gate.passing()
        if stop is not None and stop.is_set():
            return self._stopped()
        if isinstance(self._script, BaseException):
            raise self._script
        return self._script if self._script is not None else TourFound(order=model.node_item_ids)

    def _stopped(self) -> TourOutcome:
        if self._incumbents:
            return TourFound(order=self._incumbents[-1].order, ending="stopped")
        return TourStopped()

"""`TourSolver` double for unit and adapter wiring tests: it answers with a scripted outcome, in-process and at once.

Mutation runs select unit and integration tests without `solver_child`, so job states are driven by this script and not
by OR-Tools (the waivers W1/W2 stay acceptance-only). The script is a `TourOutcome`, an exception to raise, or `None`
for the tour that visits the model's nodes in order. Like the real adapter it refuses a model without nodes or a budget
that is not positive.
"""

from __future__ import annotations

import threading

from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.tour_solver import TourFound, TourOutcome
from overland_planner.domain.planning.solver_model_builder import TourModel
from tests.unit.application.planning.planning_doubles import Gate

Script = TourOutcome | BaseException | None


class ScriptedTourSolver:
    def __init__(self, script: Script = None, *, gate: Gate | None = None) -> None:
        self._script = script
        self.gate = gate or Gate()
        self.models: list[TourModel] = []
        self.budgets: list[int] = []
        self.threads: list[threading.Thread] = []

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def solve(self, model: TourModel, budget: int) -> TourOutcome:
        assert model.node_item_ids, "a model has at least the Start and End nodes"
        assert budget > 0, "the budget must be positive"
        self.models.append(model)
        self.budgets.append(budget)
        self.threads.append(threading.current_thread())
        self.gate.passing()
        if isinstance(self._script, BaseException):
            raise self._script
        return self._script if self._script is not None else TourFound(order=model.node_item_ids)

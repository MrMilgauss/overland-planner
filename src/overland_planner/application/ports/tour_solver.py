"""TourSolver port (brief §6, ADR-015): the optimizer that orders a plan's stops.

`solve(model, budget, on_incumbent)` streams each valid incumbent to `on_incumbent` while it searches, then answers with
a typed outcome; limits and Stop arrive with 06-07 and 06-08. A found tour speaks item ids: `order` runs from Start to
End (a round trip names the same id at both ends) and `visited_item_ids` is what `PlanRunAssembler.assemble` takes.
`ending` says how a found tour's search ended: `budget` (its count-based stop, the only reproducible ending, D42) or
`optimizer_failed` (the child ended abnormally after an incumbent: the last one, D122); `time_limit` and `stopped` come
next. Reason codes are fixed by ADR-015 (D122).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol

from overland_planner.application.ports.probe import Probeable
from overland_planner.domain.planning.run_messages import NotFullyOptimised
from overland_planner.domain.planning.solver_model_builder import TourModel

TourEnding = Literal["budget"] | NotFullyOptimised


@dataclass(frozen=True)
class Incumbent:
    """A valid tour found while searching: its order in item ids and the model's cost of it (metres today).

    `unconfirmed_legs` and `retraces` stay 0 until slices 06a/06b give the model levels and retrace arcs.
    """

    order: tuple[str, ...]
    objective: float
    unconfirmed_legs: int = 0
    retraces: int = 0


IncumbentObserver = Callable[[Incumbent], None]


def ignore_incumbents(_incumbent: Incumbent) -> None:
    """The observer of a solve nobody follows."""


@dataclass(frozen=True)
class TourFound:
    order: tuple[str, ...]
    ending: TourEnding = "budget"

    @property
    def visited_item_ids(self) -> tuple[str, ...]:
        return self.order[1:-1]

    @property
    def reproducible(self) -> bool:
        return self.ending == "budget"

    @property
    def not_fully_optimised(self) -> NotFullyOptimised | None:
        match self.ending:
            case "budget":
                return None
            case other:
                return other


@dataclass(frozen=True)
class TourNoRoute:
    reason: ClassVar[str] = "no_valid_route_found"
    reproducible: ClassVar[bool] = True  # the search ended on its own


@dataclass(frozen=True)
class TourOptimizerFailed:
    """The child ended abnormally. `signal` is set when a signal ended it, `exit_code` when it exited (ADR-015)."""

    exit_code: int | None
    signal: int | None
    reason: ClassVar[str] = "optimizer_failed"
    reproducible: ClassVar[bool] = False


@dataclass(frozen=True)
class TourTimedOut:
    reason: ClassVar[str] = "timeout"
    reproducible: ClassVar[bool] = False


TourOutcome = TourFound | TourNoRoute | TourOptimizerFailed | TourTimedOut


class TourSolver(Probeable, Protocol):
    """`identity` names what makes this solver's orders what they are (ADR-014 section 5): the fingerprint memo keys by
    it, so another solver never reuses this one's orders."""

    identity: str

    def solve(self, model: TourModel, budget: int, on_incumbent: IncumbentObserver = ...) -> TourOutcome: ...

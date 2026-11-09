"""TourSolver port (brief §6, ADR-015): the optimizer that orders a plan's stops.

Slice 01b declares the subset `solve(model, budget) -> typed outcome`; limits, Stop and incumbents arrive with slice 03.
A found tour speaks item ids: `order` runs from Start to End (a round trip names the same id at both ends) and
`visited_item_ids` is what `PlanRunAssembler.assemble` takes. Reason codes are fixed by ADR-015 (D122).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol

from overland_planner.application.ports.probe import Probeable
from overland_planner.domain.planning.solver_model_builder import TourModel


@dataclass(frozen=True)
class TourFound:
    order: tuple[str, ...]

    @property
    def visited_item_ids(self) -> tuple[str, ...]:
        return self.order[1:-1]


@dataclass(frozen=True)
class TourNoRoute:
    reason: ClassVar[str] = "no_valid_route_found"


@dataclass(frozen=True)
class TourOptimizerFailed:
    """The child ended abnormally. `signal` is set when a signal ended it, `exit_code` when it exited (ADR-015)."""

    exit_code: int | None
    signal: int | None
    reason: ClassVar[str] = "optimizer_failed"


@dataclass(frozen=True)
class TourTimedOut:
    reason: ClassVar[str] = "timeout"


TourOutcome = TourFound | TourNoRoute | TourOptimizerFailed | TourTimedOut


class TourSolver(Probeable, Protocol):
    """`identity` names what makes this solver's orders what they are (ADR-014 section 5): the fingerprint memo keys by
    it, so another solver never reuses this one's orders."""

    identity: str

    def solve(self, model: TourModel, budget: int) -> TourOutcome: ...

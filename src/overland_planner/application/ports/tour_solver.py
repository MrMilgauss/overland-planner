"""TourSolver port (brief §6, ADR-015): the optimizer that orders a plan's stops.

`solve(model, budget, on_incumbent, deadlines=..., stop=...)` streams each valid incumbent to `on_incumbent` while it
searches, then answers with a typed outcome. A found tour speaks item ids: `order` runs from Start to End (a round trip
names the same id at both ends) and `visited_item_ids` is what `PlanRunAssembler.assemble` takes. `ending` says how a
found tour's search ended: `budget` (its count-based stop, the only reproducible ending, D42), `optimizer_failed` (the
child ended abnormally after an incumbent: the last one, D122), `time_limit` (the optimisation deadline came with an
incumbent: the last one) or `stopped` (Marco pressed Stop after an incumbent: the last one, D60). Reason codes are fixed
by ADR-015 (D122).

Stop reaches the solve through its stop signal (brief section 6): once `stop.is_set()` the solve ends as soon as it can
with the last valid incumbent labelled `stopped`, or Failed `stopped` without one (`TourStopped`). A `threading.Event`
is a stop signal.

The limits (ADR-014 section 2, D41, D58, D200) are whole seconds from pressing Calculate: without an incumbent the solve
ends at the feasibility deadline (Failed `timeout`), with one at the optimisation deadline (`time_limit`). The job turns
its `SolveLimits` into `SolveDeadlines`, instants on the `Clock` port's monotonic time measured from the job's start, so
the road legs and the wait for the solver slot count; the feasibility limit never exceeds the optimisation limit (D116).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol

from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.probe import Probeable
from overland_planner.domain.planning.run_messages import NotFullyOptimised
from overland_planner.domain.planning.solver_model_builder import TourModel

TourEnding = Literal["budget"] | NotFullyOptimised
DEFAULT_FEASIBILITY_LIMIT_S = 600
DEFAULT_OPTIMISATION_LIMIT_S = 1800


class StopSignal(Protocol):
    def is_set(self) -> bool: ...


class _NeverStopped:
    def is_set(self) -> bool:
        return False


NEVER_STOPPED: StopSignal = _NeverStopped()  # the stop signal of a solve nobody can stop


@dataclass(frozen=True)
class SolveDeadlines:
    """The two deadlines of a solve, instants on `clock`'s monotonic time (`feasibility_s <= optimisation_s`)."""

    clock: Clock
    feasibility_s: float
    optimisation_s: float

    def remaining_s(self, *, found: bool) -> float:
        """Seconds left before the deadline that applies: the optimisation one once a valid route was `found`."""
        deadline = self.optimisation_s if found else self.feasibility_s
        return deadline - self.clock.monotonic()


@dataclass(frozen=True)
class SolveLimits:
    """The feasibility and optimisation limits in whole seconds from the job's start (ADR-014 section 2)."""

    feasibility_s: int = DEFAULT_FEASIBILITY_LIMIT_S
    optimisation_s: int = DEFAULT_OPTIMISATION_LIMIT_S

    def from_start(self, clock: Clock, started_s: float) -> SolveDeadlines:
        return SolveDeadlines(clock, started_s + self.feasibility_s, started_s + self.optimisation_s)


@dataclass(frozen=True)
class Incumbent:
    """A valid tour found while searching: its order in item ids and the cost the solver gave it.

    The job shows the tour as the model's real tables describe it (road metres, Unconfirmed legs, retraces), not this
    cost, which may weigh them (07-08); a model without real tables is shown as it came.
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


@dataclass(frozen=True)
class TourStopped:
    """Stopped before a valid route was found (ADR-015)."""

    reason: ClassVar[str] = "stopped"
    reproducible: ClassVar[bool] = False


TourOutcome = TourFound | TourNoRoute | TourOptimizerFailed | TourTimedOut | TourStopped


class TourSolver(Probeable, Protocol):
    """`identity` names what makes this solver's orders what they are (ADR-014 section 5): the fingerprint memo keys by
    it, so another solver never reuses this one's orders."""

    identity: str

    def solve(
        self,
        model: TourModel,
        budget: int,
        on_incumbent: IncumbentObserver = ...,
        *,
        deadlines: SolveDeadlines,
        stop: StopSignal = ...,
    ) -> TourOutcome: ...

"""Plan assembly (brief section 4): a chosen order of the Included items becomes the ordered stops. Pure domain.

The first stop is the Start and the last the End (HC-2); each later stop carries the road leg, km and time, from where
the previous stop is left to where it is reached (HC-1); a track stop carries its length and off-road time at the
project's off-road speed, and every stop its cumulative km and time to its end (FR-6.1, D11). `Totals.of` the stops are
the plan's totals (FR-6.2). Checking the chosen order is the guard's job (brief section 8), not this assembler's.
A Failed run's report keeps its reason in product words, mapped from the stored code (D206); a code with no product
wording yet shows its words (D220 e). A ready run has no report until slice 04 brings the consideration report; the
warnings arrive with later slices.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from overland_planner.domain.catalog.item import CatalogItem
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot, road_between
from overland_planner.domain.routing.road_leg import LegTable

_PRODUCT_WORDS = {
    "internal_invariant_violation": "internal invariant violation",
    "no_valid_route_found": "no valid route found",
    "optimizer_failed": "optimizer failed",
    "timeout": "timeout",
}


@dataclass(frozen=True)
class PlanReport:
    """The minimal consideration report (US-07b completes it): why a Failed run has no plan."""

    reason: str


class PlanRunAssembler:
    def __init__(self, snapshot: ProjectSnapshot, legs: LegTable) -> None:
        self._snapshot = snapshot
        self._legs = legs

    def assemble(self, visited_item_ids: Sequence[str]) -> tuple[PlanStop, ...]:
        trip = (self._snapshot.start(), *map(self._snapshot.item, visited_item_ids), self._snapshot.end())
        stops: list[PlanStop] = []
        for previous, item in zip((None, *trip[:-1]), trip, strict=True):
            stops.append(self._stop(item, previous).ending(stops))
        return tuple(stops)

    @staticmethod
    def report(failure_reason: str | None) -> PlanReport | None:
        """`None` for a ready run; a code the planner does not store is a bug, so it raises `KeyError`."""
        return None if failure_reason is None else PlanReport(_PRODUCT_WORDS[failure_reason])

    def _stop(self, item: CatalogItem, previous: CatalogItem | None) -> PlanStop:
        leg = None if previous is None else self._legs.km_and_s(*road_between(previous, item))
        return PlanStop.driving(item, leg, self._snapshot.offroad_speed)

"""Plan assembly (brief section 4): a chosen order of the Included items becomes the ordered stops. Pure domain.

The first stop is the Start and the last the End (HC-2); each later stop carries the road leg, km and time, from where
the previous stop is left to where it is reached (HC-1), with its confidence level; a track whose exit has no road to
the next stop is followed by its retrace row and the road goes on from its entry (ADR-017 section 3); a track stop
carries its length and off-road time at the project's off-road speed, and every stop its cumulative km and time to its
end (FR-6.1, D11). `Totals.of` the stops are the plan's totals (FR-6.2). Checking the chosen order is the guard's job
(brief section 8), not this assembler's.
A Failed run's report keeps its reason in product words, mapped from the stored code (D206); a code with no product
wording yet shows its words (D220 e). A ready run has no report until slice 04 brings the consideration report; the
warnings arrive with later slices.
"""

from __future__ import annotations

from collections.abc import Sequence

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.planning.plan_run import PlanReport, PlanStop
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot, left_at, reached_at
from overland_planner.domain.planning.retrace_rule import arc_kind
from overland_planner.domain.routing.road_leg import LegTable, RoadPair

_PRODUCT_WORDS = {
    "internal_invariant_violation": "internal invariant violation",
    "no_valid_route_found": "no valid route found",
    "optimizer_failed": "optimizer failed",
    "timeout": "timeout",
    "unreachable": "unreachable",
}


class PlanRunAssembler:
    def __init__(self, snapshot: ProjectSnapshot, legs: LegTable) -> None:
        self._snapshot = snapshot
        self._legs = legs

    def assemble(self, visited_item_ids: Sequence[str]) -> tuple[PlanStop, ...]:
        trip = (self._snapshot.start(), *map(self._snapshot.item, visited_item_ids), self._snapshot.end())
        stops: list[PlanStop] = []
        for previous, item in zip((None, *trip[:-1]), trip, strict=True):
            for stop in self._arrival(item, previous):
                stops.append(stop.ending(stops))
        return tuple(stops)

    @staticmethod
    def report(failure_reason: str | None, items: Sequence[str] = ()) -> PlanReport | None:
        """`None` for a ready run; a code with no product wording yet shows its words (D220 e). `items` are the names
        an `unreachable` run is about."""
        if failure_reason is None:
            return None
        return PlanReport(_PRODUCT_WORDS.get(failure_reason, failure_reason.replace("_", " ")), tuple(items))

    def _arrival(self, item: CatalogItem, previous: CatalogItem | None) -> list[PlanStop]:
        """The stops that reach `item`: its retrace row first when `previous` is a track retraced to leave (the rule is
        the model's, `retrace_rule.arc_kind`), then the item with the road leg from where the previous is left."""
        if previous is None:
            return [PlanStop.driving(item, None, self._snapshot.offroad_speed)]
        if isinstance(previous, TrackItem) and arc_kind(previous, item, self._legs) == "retrace":
            return [PlanStop.retracing(previous, self._snapshot.offroad_speed), self._reached(item, previous.entry)]
        return [self._reached(item, left_at(previous))]

    def _reached(self, item: CatalogItem, origin: Coordinate) -> PlanStop:
        road: RoadPair = origin, reached_at(item)
        level = self._legs.level(*road), self._legs.reason(*road)
        return PlanStop.driving(item, self._legs.km_and_s(*road), self._snapshot.offroad_speed, level)

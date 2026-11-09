"""Plan assembly (brief section 4): a chosen order of the Included items becomes the ordered stops. Pure domain.

The first stop is the Start and the last the End (HC-2); each later stop carries the road leg, km and time, from where
the previous stop is left to where it is reached (HC-1); a track stop carries its length and off-road time at the
project's off-road speed, and every stop its cumulative km and time to its end (FR-6.1, D11). `Totals.of` the stops are
the plan's totals (FR-6.2). Checking the chosen order is the guard's job (brief section 8), not this assembler's. The
report and warnings arrive with later slices.
"""

from __future__ import annotations

from collections.abc import Sequence

from overland_planner.domain.catalog.item import CatalogItem
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot, left_at, reached_at
from overland_planner.domain.routing.road_leg import LegTable


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

    def _stop(self, item: CatalogItem, previous: CatalogItem | None) -> PlanStop:
        if previous is None:
            return PlanStop.driving(item, None, self._snapshot.offroad_speed)
        origin, destination = left_at(previous), reached_at(item)
        leg = self._legs.distance_km(origin, destination), self._legs.duration_s(origin, destination)
        return PlanStop.driving(item, leg, self._snapshot.offroad_speed)

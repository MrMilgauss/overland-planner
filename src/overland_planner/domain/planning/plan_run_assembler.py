"""Plan assembly (brief section 4): a chosen order of the Included items becomes the ordered stops. Pure domain.

The first stop is the Start and the last the End (HC-2); each later stop carries the road leg from where the previous
stop is left to where it is reached (HC-1). Checking the chosen order is the guard's job (brief section 8), not this
assembler's. Totals, report and warnings arrive with later slices.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from overland_planner.domain.catalog.item import CatalogItem
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot, left_at, reached_at
from overland_planner.domain.routing.road_leg import LegTable

_METRES_PER_KM = 1000


class PlanRunAssembler:
    def __init__(self, snapshot: ProjectSnapshot, legs: LegTable) -> None:
        self._snapshot = snapshot
        self._legs = legs

    def assemble(self, order: Sequence[str]) -> tuple[PlanStop, ...]:
        """`order` holds the ids of the Included non-anchor items, without Start and End."""
        trip = (self._snapshot.start(), *map(self._snapshot.item, order), self._snapshot.end())
        later_stops = (PlanStop.of(item, self._leg_km(previous, item)) for previous, item in pairwise(trip))
        return (PlanStop.of(trip[0], None), *later_stops)

    def _leg_km(self, previous: CatalogItem, item: CatalogItem) -> float:
        return self._legs.distance_m(left_at(previous), reached_at(item)) / _METRES_PER_KM

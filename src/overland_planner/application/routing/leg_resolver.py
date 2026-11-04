"""Leg resolver (brief section 8): the road legs of a plan, from the road map.

The seam for the confidence ladder and the leg cache (slices 05 and 06b). Today it asks for the required pairs: each
distinct pair once, grouped by origin so that no pair outside the request is asked. Identical points need no road map,
because nothing is driven between them (`LegTable` answers 0 m).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from overland_planner.application.ports.routing_provider import RoutingProvider
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg, RoadPair


class LegResolver:
    def __init__(self, provider: RoutingProvider) -> None:
        self._provider = provider

    @property
    def provider_id(self) -> str:
        return self._provider.provider_id

    def resolve(self, pairs: Iterable[RoadPair]) -> LegTable:
        """A table that covers every pair; a road map failure propagates."""
        targets_by_origin: dict[Coordinate, list[Coordinate]] = {}
        for origin, destination in dict.fromkeys(pairs):
            if origin != destination:
                targets_by_origin.setdefault(origin, []).append(destination)
        return LegTable(leg for origin, targets in targets_by_origin.items() for leg in self._legs(origin, targets))

    def _legs(self, origin: Coordinate, targets: list[Coordinate]) -> Iterator[RoadLeg]:
        (row,) = self._provider.matrix([origin], targets)
        for target, distance_m in zip(targets, row, strict=True):
            yield RoadLeg(origin, target, distance_m)

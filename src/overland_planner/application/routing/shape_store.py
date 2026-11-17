"""Shape store (ADR-007 Amendment 2, D252): the road shapes of a map, kept once found.

It asks the road map for the shape of a pair it does not hold and keeps the answer in memory for the store's life,
which is the planner process's: per provider_id, profile and pair, as the legs are (D244), the identity read once by
the caller. A shape that is not available (a straight line standing for no road) is never kept, so the road map is
asked again next time. Safe across threads; the lock is never held while the road map is asked.
"""

from __future__ import annotations

import threading

from overland_planner.application.ports.routing_provider import RoutingProvider
from overland_planner.application.routing.leg_resolver import RoadMapKey
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import RoadPair
from overland_planner.domain.routing.road_shape import RoadShape


class ShapeStore:
    def __init__(self, provider: RoutingProvider) -> None:
        self._provider = provider
        self._kept: dict[tuple[RoadMapKey, RoadPair], RoadShape] = {}
        self._lock = threading.Lock()

    def shape(self, origin: Coordinate, destination: Coordinate, *, road_map: RoadMapKey) -> RoadShape:
        key = (road_map, (origin, destination))
        with self._lock:
            held = self._kept.get(key)
        if held is not None:
            return held
        found = self._provider.route_shape(origin, destination)
        if found.available:
            with self._lock:
                self._kept[key] = found
        return found

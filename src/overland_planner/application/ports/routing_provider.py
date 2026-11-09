"""RoutingProvider port (brief section 6): the road map that gives the distance and road time of a road leg.

Slice 01b declares the subset `provider_id` and `matrix(sources, targets)`; `locate`, `route_many`, modes, `None` cells
and typed errors arrive with slice 06a. Each cell holds the distance in integer metres and the road time in seconds.
`provider_id` names the road map, so legs and plans of different road maps are never confused.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from overland_planner.application.ports.probe import Probeable
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import RoadMeasure


class RoutingProvider(Probeable, Protocol):
    @property
    def provider_id(self) -> str: ...

    def matrix(self, sources: Sequence[Coordinate], targets: Sequence[Coordinate]) -> Sequence[Sequence[RoadMeasure]]:
        """One row per source, one cell per target: the road distance in metres and the road time in seconds."""
        ...

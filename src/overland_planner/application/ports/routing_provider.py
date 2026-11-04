"""RoutingProvider port (brief section 6): the road map that gives the distance of a road leg.

Slice 01b declares the subset `provider_id` and `matrix(sources, targets)`; `locate`, `route_many`, modes, `None` cells
and typed errors arrive with slice 06a. Distances are integer metres.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from overland_planner.application.ports.probe import Probeable
from overland_planner.domain.catalog.coordinate import Coordinate


class RoutingProvider(Probeable, Protocol):
    @property
    def provider_id(self) -> str: ...

    def matrix(self, sources: Sequence[Coordinate], targets: Sequence[Coordinate]) -> Sequence[Sequence[int]]:
        """One row per source, one cell per target: the road distance in metres."""
        ...

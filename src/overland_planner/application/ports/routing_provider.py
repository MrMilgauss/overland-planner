"""RoutingProvider port (brief section 6): the road map that gives the distance and road time of a road leg.

Slice 06a declares `provider_id`, `profile`, `matrix(sources, targets, observer)` and the typed errors; `route_shape`
(slice 09, D252) answers the shape of the road between two points; `locate` and `route_many` arrive with slices 06b and
09. Each cell holds the distance in integer metres and the road time in seconds, with the level it was found at (03b); a
cell is `None` for a pair with no road at any level, and an `OffNetwork` for a pair with an end the road map cannot snap
to a road open to vehicles (it names that end or ends).
`provider_id` and `profile` name the road map and the way it routes, so legs and plans of different ones are never
confused. The observer is told of each retry the adapter makes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from overland_planner.application.ports.probe import Probeable
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import OffNetwork, RoadMeasure
from overland_planner.domain.routing.road_shape import RoadShape

RoadCell = RoadMeasure | OffNetwork | None


class RoutingObserver(Protocol):
    def retried(self) -> None: ...


class RoutingProviderError(Exception):
    """The road map failed; its subclasses say how."""


class ProviderUnreachable(RoutingProviderError):
    """The road map cannot be reached."""


class ProviderUnavailable(RoutingProviderError):
    """The road map is reached but cannot answer now."""


class ProviderRejected(RoutingProviderError):
    """The road map refused the request."""


class RoutingProvider(Probeable, Protocol):
    @property
    def provider_id(self) -> str: ...

    @property
    def profile(self) -> str: ...

    def matrix(
        self, sources: Sequence[Coordinate], targets: Sequence[Coordinate], observer: RoutingObserver | None = None
    ) -> Sequence[Sequence[RoadCell]]:
        """One row per source, one cell per target: the road distance in metres and the road time in seconds,
        or None when no road exists at any level."""
        ...

    def route_shape(self, origin: Coordinate, destination: Coordinate) -> RoadShape:
        """The shape of the road from origin to destination; the straight line, marked not available, when the road
        map has no road there; one point for identical points."""
        ...

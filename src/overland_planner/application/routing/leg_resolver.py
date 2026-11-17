"""Leg resolver (brief section 8): the road legs of a plan, from the road map, kept once found.

The seam for the confidence ladder and the persistent leg cache (slices 05 and 06b). It asks for the required pairs
it does not hold yet: each distinct pair once, one origin per road-map call with all of that origin's missing targets
(L5), so that no pair outside the request is asked, and hands on each pair's distance and road time. Identical points
need no road map, because nothing is driven between them (`LegTable` answers 0 m, 0 s).

A pair the road map answers with no road at any level is kept as such: it is never asked again, and counts as found
like any other leg. A pair it answers `OffNetwork` counts as found too and is a pair with no road in the table, but is
not kept: the place it names is asked about again in the next request (D245). Within one request the resolver remembers
those places and answers the later pairs from or to them itself, so a far place costs one question, not one per origin;
that memory ends with the request. The legs found are kept in memory for the resolver's life, which is the planner
process's (06-09): per provider_id, profile and pair (D244), safe across the jobs' threads, and never locked while the
road map is asked. The persistent `leg_cache` table is slice 05's; until then a restart forgets them (a recorded
deviation from ADR-015). A request reports the legs it already holds before it asks anything (`cached`, identical
points included), and the legs found after every road-map call (`new`); at the end `new + cached = total`, its
distinct pairs. A leg answered is kept even when the progress that hears of it ends the request, and when the road
map fails on a later call (D248): the failure propagates, and the legs answered before it are served from the memory
next time. The `observer` is handed to every road-map call, to hear its retries.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from overland_planner.application.ports.routing_provider import RoutingObserver, RoutingProvider
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import LegTable, OffNetwork, RoadLeg, RoadMeasure, RoadPair


@dataclass(frozen=True)
class LegsFound:
    """The legs of one request so far: asked of the road map (`new`), known without asking (`cached`), all (`total`)."""

    new: int
    cached: int
    total: int


RoadMapKey = tuple[str, str]  # (provider_id, profile): the legs of one road map and profile are never served to another


def _unheard(_: LegsFound) -> None:
    return None


class LegResolver:
    def __init__(self, provider: RoutingProvider) -> None:
        self._provider = provider
        self._known: dict[tuple[RoadMapKey, RoadPair], RoadMeasure | None] = {}
        self._lock = threading.Lock()

    @property
    def provider_id(self) -> str:
        return self._provider.provider_id

    @property
    def profile(self) -> str:
        return self._provider.profile

    def identity(self) -> RoadMapKey:
        """The road map's identity as read now: one read of each, to be kept for a whole job."""
        return self.provider_id, self.profile

    def resolve(
        self,
        pairs: Iterable[RoadPair],
        progress: Callable[[LegsFound], None] = _unheard,
        observer: RoutingObserver | None = None,
        *,
        road_map: RoadMapKey | None = None,
    ) -> LegTable:
        """A table that covers every pair; a road map failure, or one raised by `progress`, propagates. A job hands
        the `road_map` identity it read once at its start, so that its legs are kept under the identity of its run;
        without one the identity is read now."""
        road_map = road_map or self.identity()
        distinct = list(dict.fromkeys(pairs))
        roads = [pair for pair in distinct if pair[0] != pair[1]]
        held = self._held(road_map, roads)
        targets_by_origin = _missing_by_origin(roads, held)
        found = LegsFound(0, len(distinct) - sum(map(len, targets_by_origin.values())), len(distinct))
        progress(found)
        off_network: set[Coordinate] = set()
        for origin, targets in targets_by_origin.items():
            answered = self._answer(road_map, origin, targets, off_network, observer)
            held.update(answered)
            found = LegsFound(found.new + len(answered), found.cached, found.total)
            progress(found)
        return _table_of(held)

    def _held(self, road_map: RoadMapKey, roads: Iterable[RoadPair]) -> dict[RoadPair, RoadMeasure | None]:
        with self._lock:
            return {pair: self._known[road_map, pair] for pair in roads if (road_map, pair) in self._known}

    def _answer(
        self,
        road_map: RoadMapKey,
        origin: Coordinate,
        targets: list[Coordinate],
        off_network: set[Coordinate],
        observer: RoutingObserver | None,
    ) -> dict[RoadPair, RoadMeasure | None]:
        """The pairs from or to a place already named off the network are answered here, the others by the road map."""
        known_far = origin in off_network
        answered: dict[RoadPair, RoadMeasure | None] = {
            (origin, target): None for target in targets if known_far or target in off_network
        }
        to_ask = [target for target in targets if (origin, target) not in answered]
        if to_ask:
            answered.update(self._ask(road_map, origin, to_ask, off_network, observer))
        return answered

    def _ask(
        self,
        road_map: RoadMapKey,
        origin: Coordinate,
        targets: list[Coordinate],
        off_network: set[Coordinate],
        observer: RoutingObserver | None,
    ) -> dict[RoadPair, RoadMeasure | None]:
        (row,) = self._provider.matrix([origin], targets, observer)
        answered: dict[RoadPair, RoadMeasure | None] = {}
        kept: dict[RoadPair, RoadMeasure | None] = {}
        for target, cell in zip(targets, row, strict=True):
            if isinstance(cell, OffNetwork):
                off_network.update(cell.places)
                answered[origin, target] = None
            else:
                kept[origin, target] = cell
        with self._lock:
            self._known.update({(road_map, pair): measure for pair, measure in kept.items()})
        return answered | kept


def _table_of(held: Mapping[RoadPair, RoadMeasure | None]) -> LegTable:
    """A pair answered with no road stays in the table as such, apart from a pair nobody asked."""
    legs = (
        RoadLeg(*pair, measure.distance_m, measure.duration_s, measure.level, measure.reason)
        for pair, measure in held.items()
        if measure is not None
    )
    return LegTable(legs, no_road=[pair for pair, measure in held.items() if measure is None])


def _missing_by_origin(
    roads: Iterable[RoadPair], held: Mapping[RoadPair, RoadMeasure | None]
) -> dict[Coordinate, list[Coordinate]]:
    """The road pairs not held, one entry per origin with its targets in request order (one road-map call each)."""
    targets_by_origin: dict[Coordinate, list[Coordinate]] = {}
    for origin, destination in roads:
        if (origin, destination) not in held:
            targets_by_origin.setdefault(origin, []).append(destination)
    return targets_by_origin

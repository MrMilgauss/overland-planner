"""Leg resolver (brief section 8): the road legs of a plan, from the road map, kept once found.

The seam for the confidence ladder and the persistent leg cache (slices 05 and 06b). It asks for the required pairs
it does not hold yet: each distinct pair once, one origin per road-map call with all of that origin's missing targets
(L5), so that no pair outside the request is asked, and hands on each pair's distance and road time. Identical points
need no road map, because nothing is driven between them (`LegTable` answers 0 m, 0 s).

The legs found are kept in memory for the resolver's life, which is the planner process's (06-09): per provider_id
and pair, safe across the jobs' threads, and never locked while the road map is asked. The persistent `leg_cache`
table is slice 05's; until then a restart forgets them (a recorded deviation from ADR-015). A request reports the legs
it already holds before it asks anything (`cached`, identical points included), and the legs found after every
road-map call (`new`); at the end `new + cached = total`, its distinct pairs. A leg answered is kept even when the
progress that hears of it ends the request.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from overland_planner.application.ports.routing_provider import RoutingProvider
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg, RoadMeasure, RoadPair


@dataclass(frozen=True)
class LegsFound:
    """The legs of one request so far: asked of the road map (`new`), known without asking (`cached`), all (`total`)."""

    new: int
    cached: int
    total: int


def _unheard(_: LegsFound) -> None:
    return None


class LegResolver:
    def __init__(self, provider: RoutingProvider) -> None:
        self._provider = provider
        self._known: dict[tuple[str, RoadPair], RoadMeasure] = {}
        self._lock = threading.Lock()

    @property
    def provider_id(self) -> str:
        return self._provider.provider_id

    def resolve(self, pairs: Iterable[RoadPair], progress: Callable[[LegsFound], None] = _unheard) -> LegTable:
        """A table that covers every pair; a road map failure, or one raised by `progress`, propagates."""
        provider_id = self.provider_id
        distinct = list(dict.fromkeys(pairs))
        roads = [pair for pair in distinct if pair[0] != pair[1]]
        held = self._held(provider_id, roads)
        targets_by_origin = _missing_by_origin(roads, held)
        found = LegsFound(0, len(distinct) - sum(map(len, targets_by_origin.values())), len(distinct))
        progress(found)
        for origin, targets in targets_by_origin.items():
            answered = self._ask(provider_id, origin, targets)
            held.update(answered)
            found = LegsFound(found.new + len(answered), found.cached, found.total)
            progress(found)
        return LegTable(RoadLeg(*pair, measure.distance_m, measure.duration_s) for pair, measure in held.items())

    def _held(self, provider_id: str, roads: Iterable[RoadPair]) -> dict[RoadPair, RoadMeasure]:
        with self._lock:
            return {pair: self._known[provider_id, pair] for pair in roads if (provider_id, pair) in self._known}

    def _ask(self, provider_id: str, origin: Coordinate, targets: list[Coordinate]) -> dict[RoadPair, RoadMeasure]:
        (row,) = self._provider.matrix([origin], targets)
        answered = {(origin, target): measure for target, measure in zip(targets, row, strict=True)}
        with self._lock:
            self._known.update({(provider_id, pair): measure for pair, measure in answered.items()})
        return answered


def _missing_by_origin(
    roads: Iterable[RoadPair], held: Mapping[RoadPair, RoadMeasure]
) -> dict[Coordinate, list[Coordinate]]:
    """The road pairs not held, one entry per origin with its targets in request order (one road-map call each)."""
    targets_by_origin: dict[Coordinate, list[Coordinate]] = {}
    for origin, destination in roads:
        if (origin, destination) not in held:
            targets_by_origin.setdefault(origin, []).append(destination)
    return targets_by_origin

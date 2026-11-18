"""The map of a stored plan run (slice 09, ADR-007 Amendment 2, D251-D254): its lines and markers in driving order.

Line features: `road` (the leg into a stop, from where the previous stop is left to where this one is reached), `track`
(entry to exit, in the direction it is driven) and `retrace` (exit back to entry); `stop` is the 1-based itinerary row
the line leads to or belongs to. Point features: a numbered `stop` marker at a place or a track's entry, the `entry` and
`exit` of each track, and the Start and End as `start`/`end`, or one `start_end` marker (carrying the End's number in
`end_stop`) when both are the same place. A retrace row is a row of the itinerary and so has a number but no marker; a
road leg between identical places has nothing to draw.

Tracks and retraces come from the canonical points of the run's direction version, thinned for display to at most
`MAX_TRACK_POINTS` (first and last kept, every n-th between), and never depend on the road map; when a track's points
cannot be read (no file, unreadable or invalid file, no direction version) it is drawn as the entry-to-exit chord and
marked `unavailable`, as is its retrace. Road shapes come from
the shape store, at most two at a time, only while the road map's identity (read once) is the run's stored
`provider_id` and `profile`; otherwise, or from the first typed failure of the road map on, a leg is the straight line
between its places marked `unavailable` and the answer is still whole. Reading changes no run. Each answer logs one
`plan.run.geometry_served`.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from overland_planner.application.catalog.facade import InvalidCanonicalPointsFileError, parse_canonical_points_file
from overland_planner.application.planning.plan_run_queries import PlanRunNotFoundError, PlanRunQueries
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.file_store import CanonicalPointsMissing, FileStore
from overland_planner.application.ports.plan_run_repository import PlanRunDetail
from overland_planner.application.ports.routing_provider import RoutingProviderError
from overland_planner.application.routing.facade import RoadMapKey, ShapeStore
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.routing.road_leg import RoadLevel
from overland_planner.domain.routing.road_shape import RoadShape

MAX_TRACK_POINTS = 1_500
_FETCHED_AT_ONCE = 2
_MS_PER_S = 1000

LineKind = Literal["road", "track", "retrace"]
MarkerKind = Literal["stop", "entry", "exit", "start_end", "start", "end"]
Geometry = Literal["available", "unavailable"]


class RunHasNoRouteError(LookupError):
    """A Failed run has no route to draw."""

    def __init__(self) -> None:
        super().__init__("This plan run has no route to draw")


@dataclass(frozen=True)
class LineFeature:
    kind: LineKind
    stop: int
    item_id: str
    name: str
    level: RoadLevel | None
    reason: str | None
    geometry: Geometry
    points: tuple[Coordinate, ...]


@dataclass(frozen=True)
class PointFeature:
    marker: MarkerKind
    stop: int
    item_id: str
    name: str
    point: Coordinate
    end_stop: int | None = None


@dataclass(frozen=True)
class RunGeometry:
    lines: tuple[LineFeature, ...]
    markers: tuple[PointFeature, ...]


@dataclass(frozen=True)
class _Trail:
    """The points to draw for a track and whether they are the trail's own (else: the entry-to-exit chord)."""

    points: tuple[Coordinate, ...]
    stored: bool


@dataclass(frozen=True)
class _Leg:
    stop: int
    into: PlanStop
    origin: Coordinate
    destination: Coordinate


def thinned(points: Sequence[Coordinate], limit: int = MAX_TRACK_POINTS) -> tuple[Coordinate, ...]:
    """At most `limit` of the points in their order, the first and the last always kept."""
    if len(points) <= limit:
        return tuple(points)
    every = math.ceil((len(points) - 1) / (limit - 1))
    return (*points[: len(points) - 1 : every], points[-1])


class RunGeometryService:
    def __init__(
        self,
        runs: PlanRunQueries,
        files: FileStore,
        shapes: ShapeStore,
        road_map_identity: Callable[[], RoadMapKey],
        event_log: EventLog,
        clock: Clock,
    ) -> None:
        self._runs = runs
        self._files = files
        self._shapes = shapes
        self._road_map_identity = road_map_identity
        self._event_log = event_log
        self._clock = clock

    def geometry(self, plan_run_id: str) -> RunGeometry:
        """Raises `PlanRunNotFoundError` for an unknown run and `RunHasNoRouteError` for a Failed one."""
        started = self._clock.monotonic()
        run = self._runs.get(plan_run_id)
        if run is None:
            raise PlanRunNotFoundError(plan_run_id)
        if run.status == "failed":
            raise RunHasNoRouteError
        legs = _legs_of(run.stops)
        shapes = self._road_shapes(run, legs)
        tracks = self._tracks(run.stops)
        lines = tuple(self._lines(run.stops, legs, shapes, tracks))
        fetched = sum(1 for shape in shapes if shape.available)
        self._event_log.info(
            "plan.run.geometry_served",
            plan_run_id=run.id,
            legs=len(legs),
            legs_fetched=fetched,
            unavailable=len(legs) - fetched,
            served_ms=int((self._clock.monotonic() - started) * _MS_PER_S),
        )
        return RunGeometry(lines, tuple(_markers_of(run.stops)))

    def _road_shapes(self, run: PlanRunDetail, legs: Sequence[_Leg]) -> list[RoadShape]:
        straight = [RoadShape.straight_line(leg.origin, leg.destination, available=False) for leg in legs]
        road_map = self._same_road_map(run)
        if road_map is None or not legs:
            return straight
        shapes: list[RoadShape] = []
        failed = False
        with ThreadPoolExecutor(max_workers=_FETCHED_AT_ONCE) as pool:
            futures = [pool.submit(self._shapes.shape, leg.origin, leg.destination, road_map=road_map) for leg in legs]
            for future, fallback in zip(futures, straight, strict=True):
                if failed and future.cancel():
                    shapes.append(fallback)
                    continue
                try:
                    shapes.append(future.result())
                except RoutingProviderError:
                    failed = True
                    shapes.append(fallback)
        return shapes

    def _same_road_map(self, run: PlanRunDetail) -> RoadMapKey | None:
        """The road map's identity, read once, when it is the one the run was planned on."""
        try:
            identity = self._road_map_identity()
        except RoutingProviderError:
            return None
        return identity if identity == (run.provider_id, run.profile) else None

    def _tracks(self, stops: Sequence[PlanStop]) -> dict[str, _Trail]:
        """The points of each track to draw, from the file of its run's direction version, thinned."""
        return {stop.item_id: self._track_points(stop) for stop in stops if stop.kind == "track"}

    def _track_points(self, stop: PlanStop) -> _Trail:
        """The stored points; a file that is missing, unreadable or invalid leaves the chord from entry to exit."""
        chord = _Trail((_arrival(stop), _departure(stop)), stored=False)
        if stop.direction_version is None:
            return chord
        try:
            content = self._files.read_canonical_points(stop.item_id, stop.direction_version)
            if isinstance(content, CanonicalPointsMissing):
                return chord
            points = tuple(point.coordinate for point in parse_canonical_points_file(content))
        except (OSError, InvalidCanonicalPointsFileError):
            return chord
        return _Trail(thinned(points), stored=True) if len(points) > 1 else chord

    def _lines(
        self,
        stops: Sequence[PlanStop],
        legs: Sequence[_Leg],
        shapes: Sequence[RoadShape],
        tracks: dict[str, _Trail],
    ) -> list[LineFeature]:
        roads = {leg.stop: (leg, shape) for leg, shape in zip(legs, shapes, strict=True)}
        lines: list[LineFeature] = []
        for number, stop in enumerate(stops, start=1):
            if number in roads:
                leg, shape = roads[number]
                lines.append(_road_line(leg, shape))
            if stop.kind == "track":
                lines.append(_own_line("track", number, stop, tracks[stop.item_id]))
            if stop.kind == "retrace":
                trail = tracks[stop.item_id]
                lines.append(_own_line("retrace", number, stop, _Trail(trail.points[::-1], trail.stored)))
        return lines


def _placed(place: Coordinate | None, stop: PlanStop) -> Coordinate:
    if place is None:
        raise ValueError(f"the stored stop {stop.item_id} holds no place to draw")
    return place


def _departure(stop: PlanStop) -> Coordinate:
    return _placed(stop.location if stop.kind == "poi" else stop.exit, stop)


def _arrival(stop: PlanStop) -> Coordinate:
    return _placed(stop.location if stop.kind == "poi" else stop.entry, stop)


def _legs_of(stops: Sequence[PlanStop]) -> list[_Leg]:
    """The road legs: into each stop but the first and a retrace, between places that differ."""
    legs = [
        _Leg(number, stop, _departure(before), _arrival(stop))
        for number, (before, stop) in enumerate(pairwise(stops), start=2)
        if stop.kind != "retrace"
    ]
    return [leg for leg in legs if leg.origin != leg.destination]


def _road_line(leg: _Leg, shape: RoadShape) -> LineFeature:
    geometry: Geometry = "available" if shape.available else "unavailable"
    stop = leg.into
    return LineFeature(
        "road", leg.stop, stop.item_id, stop.name, stop.leg_confidence, stop.leg_reason, geometry, shape.points
    )


def _own_line(kind: LineKind, number: int, stop: PlanStop, trail: _Trail) -> LineFeature:
    """A track or retrace line: a retrace is Unconfirmed with its reason, a track has neither; the chord drawn for a
    trail whose points cannot be read is `unavailable`."""
    geometry: Geometry = "available" if trail.stored else "unavailable"
    return LineFeature(kind, number, stop.item_id, stop.name, stop.confidence, stop.reason, geometry, trail.points)


def _markers_of(stops: Sequence[PlanStop]) -> list[PointFeature]:
    last = len(stops)
    round_trip = last > 1 and stops[0].item_id == stops[-1].item_id
    markers: list[PointFeature] = []
    for number, stop in enumerate(stops, start=1):
        if stop.kind == "retrace" or (round_trip and number == last):
            continue
        marker: MarkerKind = "stop"
        if number == 1:
            marker = "start_end" if round_trip else "start"
        elif number == last:
            marker = "end"
        end_stop = last if marker == "start_end" else None
        markers.append(PointFeature(marker, number, stop.item_id, stop.name, _arrival(stop), end_stop))
        if stop.kind == "track":
            markers.append(PointFeature("entry", number, stop.item_id, stop.name, _arrival(stop)))
            markers.append(PointFeature("exit", number, stop.item_id, stop.name, _departure(stop)))
    return markers

"""A stored itinerary becomes a GPX document (D10, ADR-010, slice 01b). Pure domain.

Waypoints: one per POI item in itinerary order, named as the item; a round-trip anchor, one item both first and last,
is one waypoint named "<name> (S/E)". Tracks, in itinerary order: every stop but the first is reached by its road leg
"Leg k: A -> B", straight from where A is left to where B is reached, also when the two are the same point; a trail
follows with its own stored points. A retrace row (ADR-017 section 3) builds no road leg into it: it is written right
after its trail as its own track, kind `retrace`, the trail's stored points reversed (the only track written
reversed), and the next road leg leaves where the retrace ends. A trail's `number` is its stop and a leg's is the stop
it leaves. A leg that is Unconfirmed, retrace or road, ends its name with "[UNCONFIRMED - <reason>]" (FR-5.8).
Slice 11 adds the report, the stale label, the stop positions and the provider's road shapes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.export.gpx_document import GpxDocument, GpxTrack, GpxWaypoint
from overland_planner.domain.planning.plan_run import PlanStop

_ROUND_TRIP_SUFFIX = " (S/E)"
_ROAD = "road"
_OFFROAD = "offroad"
_RETRACE = "retrace"
_UNCONFIRMED = "unconfirmed"


class StopWithoutPlaceError(ValueError):
    """A stored stop names no coordinate where the document needs one."""

    def __init__(self, item_id: str) -> None:
        super().__init__(f"stop {item_id}: the stop names no place")


@dataclass(frozen=True)
class GpxDocumentBuilder:
    """`trail_points` holds the stored points of every track stop, by item id."""

    run_number: int
    stops: tuple[PlanStop, ...]
    trail_points: Mapping[str, tuple[TrackPoint, ...]]

    def build(self) -> GpxDocument:
        """Raises `StopWithoutPlaceError` when a stop has lost a coordinate the document needs."""
        return GpxDocument(name=f"Plan run #{self.run_number}", waypoints=self._waypoints(), tracks=self._tracks())

    def _waypoints(self) -> tuple[GpxWaypoint, ...]:
        places = {stop.item_id: stop for stop in self.stops if stop.kind == "poi"}
        return tuple(GpxWaypoint(self._waypoint_name(stop), _placed(stop, stop.location)) for stop in places.values())

    def _waypoint_name(self, stop: PlanStop) -> str:
        return f"{stop.name}{_ROUND_TRIP_SUFFIX}" if self._is_round_trip_anchor(stop) else stop.name

    def _is_round_trip_anchor(self, stop: PlanStop) -> bool:
        first, last = self.stops[0], self.stops[-1]
        return len(self.stops) > 1 and first.item_id == last.item_id == stop.item_id

    def _tracks(self) -> tuple[GpxTrack, ...]:
        tracks: list[GpxTrack] = []
        legs = 0
        for number, stop in enumerate(self.stops, start=1):
            if stop.kind == _RETRACE:
                tracks.append(self._retrace(number, stop))
                continue
            if number > 1:
                legs += 1
                tracks.append(_road_leg(legs, number - 1, self.stops[number - 2], stop))
            if stop.kind == "track":
                tracks.append(GpxTrack(stop.name, self.trail_points[stop.item_id], number=number, kind=_OFFROAD))
        return tuple(tracks)

    def _retrace(self, number: int, stop: PlanStop) -> GpxTrack:
        points = tuple(reversed(self.trail_points[stop.item_id]))
        return GpxTrack(_marked(stop.name, stop.confidence, stop.reason), points, number=number, kind=_RETRACE)


def _road_leg(leg: int, number: int, origin: PlanStop, destination: PlanStop) -> GpxTrack:
    left = origin.location if origin.kind == "poi" else origin.exit
    reached = destination.entry if destination.kind == "track" else destination.location
    name = f"Leg {leg}: {origin.name} -> {destination.name}"
    return GpxTrack(
        _marked(name, destination.leg_confidence, destination.leg_reason),
        (TrackPoint(_placed(origin, left)), TrackPoint(_placed(destination, reached))),
        number=number,
        kind=_ROAD,
    )


def _marked(name: str, confidence: str | None, reason: str | None) -> str:
    if confidence != _UNCONFIRMED:
        return name
    return f"{name} [UNCONFIRMED - {reason}]" if reason else f"{name} [UNCONFIRMED]"


def _placed(stop: PlanStop, place: Coordinate | None) -> Coordinate:
    if place is None:
        raise StopWithoutPlaceError(stop.item_id)
    return place

"""A stored itinerary becomes a GPX document (D10, ADR-010, slice 01b). Pure domain.

Waypoints: one per POI item in itinerary order, named as the item; a round-trip anchor, one item both first and last,
is one waypoint named "<name> (S/E)". Tracks, in itinerary order: every stop but the first is reached by its road leg
"Leg k: A -> B", straight from where A is left to where B is reached, also when the two are the same point; a trail
follows with its own stored points. A trail's `number` is its stop and a leg's is the stop it leaves.
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
        return tuple(
            track for number, stop in enumerate(self.stops, start=1) for track in self._tracks_reaching(number, stop)
        )

    def _tracks_reaching(self, number: int, stop: PlanStop) -> tuple[GpxTrack, ...]:
        leg = () if number == 1 else (_road_leg(number - 1, self.stops[number - 2], stop),)
        trail = (self._trail(number, stop),) if stop.kind == "track" else ()
        return (*leg, *trail)

    def _trail(self, number: int, stop: PlanStop) -> GpxTrack:
        return GpxTrack(stop.name, self.trail_points[stop.item_id], number=number, kind=_OFFROAD)


def _road_leg(leg: int, origin: PlanStop, destination: PlanStop) -> GpxTrack:
    left = origin.exit if origin.kind == "track" else origin.location
    reached = destination.entry if destination.kind == "track" else destination.location
    return GpxTrack(
        f"Leg {leg}: {origin.name} -> {destination.name}",
        (TrackPoint(_placed(origin, left)), TrackPoint(_placed(destination, reached))),
        number=leg,
        kind=_ROAD,
    )


def _placed(stop: PlanStop, place: Coordinate | None) -> Coordinate:
    if place is None:
        raise StopWithoutPlaceError(stop.item_id)
    return place

"""A plain GPX document (brief §6, ADR-010): what a file holds, in file order, with no I/O and no format rules.

Waypoints and tracks stay in the order given and each track's points are its full sequence (HC-1): nothing here sorts,
simplifies or thins. Names are the stored names; what a file format cannot carry is the writer's concern (D205).
A track has no time per point: the canonical format stores latitude, longitude and elevation only.
"""

from __future__ import annotations

from dataclasses import dataclass

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.track import TrackPoint


@dataclass(frozen=True)
class GpxWaypoint:
    name: str
    location: Coordinate
    description: str | None = None


@dataclass(frozen=True)
class GpxTrack:
    """`number` is the itinerary stop and `kind` the file's track type (`road`, `offroad`, `retrace`; ADR-010)."""

    name: str
    points: tuple[TrackPoint, ...]
    description: str | None = None
    number: int | None = None
    kind: str | None = None


@dataclass(frozen=True)
class GpxDocument:
    """`name` and `description` are the file's own: the plan run label and the consideration report (ADR-010)."""

    name: str | None = None
    description: str | None = None
    waypoints: tuple[GpxWaypoint, ...] = ()
    tracks: tuple[GpxTrack, ...] = ()

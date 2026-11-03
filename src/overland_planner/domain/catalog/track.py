"""A recorded track point (brief §4). Pure domain: standard library only (import-linter 2/5)."""

from __future__ import annotations

from dataclasses import dataclass

from overland_planner.domain.catalog.coordinate import Coordinate


@dataclass(frozen=True)
class TrackPoint:
    """One recorded point of a track: a range-checked coordinate and an optional elevation in metres."""

    coordinate: Coordinate
    elevation_m: float | None = None

    @classmethod
    def at(cls, latitude: float, longitude: float, elevation_m: float | None = None) -> TrackPoint:
        return cls(Coordinate(latitude, longitude), elevation_m)

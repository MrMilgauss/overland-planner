"""Geofabrik .poly parser (D302): name line, then rings (`N` outline, `!N` hole) closed by END, file closed by END."""

from __future__ import annotations

from overland_planner.domain.catalog.coordinate import Coordinate, CoordinateOutOfRangeError
from overland_planner.domain.roadmap.outline import Outline

MIN_RING_POINTS = 3


class PolyParseError(ValueError):
    """The .poly text is not a valid Geofabrik polygon file."""


def parse_poly(text: str) -> Outline:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise PolyParseError("A .poly file needs a name line and rings")
    rings: list[tuple[Coordinate, ...]] = []
    holes: list[tuple[Coordinate, ...]] = []
    body = iter(lines[1:])
    for header in body:
        if header == "END":
            if not rings and not holes:
                raise PolyParseError("The .poly file has no ring")
            return Outline(rings=tuple(rings), holes=tuple(holes))
        points: list[Coordinate] = []
        for line in body:
            if line == "END":
                break
            points.append(_point(line))
        else:
            raise PolyParseError("A ring in the .poly file has no closing END")
        if len(points) < MIN_RING_POINTS:
            raise PolyParseError("A ring in the .poly file has fewer than 3 points")
        (holes if header.startswith("!") else rings).append(tuple(points))
    raise PolyParseError("The .poly file has no closing END")


def _point(line: str) -> Coordinate:
    parts = line.split()
    try:
        lon, lat = (float(part) for part in parts)
        return Coordinate(latitude=lat, longitude=lon)
    except (ValueError, CoordinateOutOfRangeError) as error:
        raise PolyParseError(f"Not a longitude/latitude point: {line!r}") from error

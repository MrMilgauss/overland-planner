"""`GpxWriter` adapter (brief §6, ADR-010): a plain document becomes GPX 1.1 bytes through gpxpy.

Everything stays in the given order and no point is sorted, simplified or thinned (HC-1). Coordinates and elevations
are written at 6 decimals; an elevation that is not a finite number is left out, because `xsd:decimal` has no such
value. POI names are not restricted at import, so characters XML 1.0 forbids are dropped from the written text; the
stored name is unchanged (D205). Text with nothing left is not written at all: gpxpy would skip an empty `<metadata>`
but keep an empty `<name>` elsewhere. The creator is fixed and there is no metadata time, so the same document gives
the same bytes.

Start-up probe (fatal, component `gpx_writer`): gpxpy formats floats itself and `xsd:decimal` rejects scientific
notation, so an embedded document with near-zero coordinates and names with `&`, `'` and accents is written and
re-parsed with defusedxml. Its elements, numbers, points and names must come back as given.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from functools import cache
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as safe_xml
import gpxpy.gpx

from overland_planner.application.ports.probe import ProbeCheck, ProbeResult, first_failure
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.export.gpx_document import GpxDocument, GpxTrack, GpxWaypoint

CREATOR = "overland-planner"
DECIMAL_PLACES = 6

_FORBIDDEN_IN_XML = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")

_NS = "{http://www.topografix.com/GPX/1/1}"
_WRITTEN_ELEMENTS = frozenset(
    f"{_NS}{tag}"
    for tag in ("gpx", "metadata", "name", "desc", "wpt", "trk", "number", "type", "trkseg", "trkpt", "ele")
)
_LOCATED_ELEMENTS = frozenset({f"{_NS}wpt", f"{_NS}trkpt"})
_PLAIN_DECIMAL = re.compile(r"-?\d+(\.\d{1,6})?")

_PROBE_DOCUMENT = GpxDocument(
    name="Prova d'avvio & verifica",
    waypoints=(
        GpxWaypoint("Caffè dell'Alpe & Rifugio", Coordinate(0.000001, -0.00001)),
        GpxWaypoint("Briançon", Coordinate(44.8986, 6.6419)),
    ),
    tracks=(
        GpxTrack(
            "Colle dell'Àssietta & Finestre",
            (
                TrackPoint.at(45.0560004, 7.041, 1650.0),
                TrackPoint.at(0.00001, -0.00002, 0.00001),
                TrackPoint.at(44.958, 6.879),
            ),
        ),
        GpxTrack("Névache", (TrackPoint.at(45.02, 6.6), TrackPoint.at(45.01, 6.7, 1590.5))),
    ),
)
_PROBE_NAMES = (
    "Prova d'avvio & verifica",
    "Caffè dell'Alpe & Rifugio",
    "Briançon",
    "Colle dell'Àssietta & Finestre",
    "Névache",
)
_PROBE_POINTS = (  # waypoints first, then track points: file order
    (Decimal("0.000001"), Decimal("-0.00001"), None),
    (Decimal("44.8986"), Decimal("6.6419"), None),
    (Decimal("45.056"), Decimal("7.041"), Decimal("1650")),
    (Decimal("0.00001"), Decimal("-0.00002"), Decimal("0.00001")),
    (Decimal("44.958"), Decimal("6.879"), None),
    (Decimal("45.02"), Decimal("6.6"), None),
    (Decimal("45.01"), Decimal("6.7"), Decimal("1590.5")),
)


class GpxpyWriter:
    def write(self, document: GpxDocument) -> bytes:
        gpx = gpxpy.gpx.GPX()
        gpx.creator = CREATOR
        gpx.name = _xml_text(document.name)
        gpx.description = _xml_text(document.description)
        gpx.waypoints = [_waypoint(waypoint) for waypoint in document.waypoints]
        gpx.tracks = [_track(track) for track in document.tracks]
        return gpx.to_xml(version="1.1").encode("utf-8")

    def probe(self) -> ProbeResult:
        @cache
        def read_back() -> Element:
            root: Element = safe_xml.fromstring(
                self.write(_PROBE_DOCUMENT), forbid_dtd=True, forbid_entities=True, forbid_external=True
            )
            return root

        return first_failure(
            [
                ProbeCheck("gpx_writer_round_trip_failed", lambda: read_back() is not None),
                ProbeCheck("gpx_writer_foreign_element", lambda: _holds_only_written_elements(read_back())),
                ProbeCheck("gpx_writer_invalid_number", lambda: _numbers_are_plain_decimals(read_back())),
                ProbeCheck("gpx_writer_points_changed", lambda: _points_of(read_back()) == _PROBE_POINTS),
                ProbeCheck("gpx_writer_names_changed", lambda: _names_of(read_back()) == _PROBE_NAMES),
            ],
            failing_errors=(Exception,),
        )


def _waypoint(waypoint: GpxWaypoint) -> gpxpy.gpx.GPXWaypoint:
    return gpxpy.gpx.GPXWaypoint(
        latitude=_at_six_decimals(waypoint.location.latitude),
        longitude=_at_six_decimals(waypoint.location.longitude),
        name=_xml_text(waypoint.name),
        description=_xml_text(waypoint.description),
    )


def _track(track: GpxTrack) -> gpxpy.gpx.GPXTrack:
    written = gpxpy.gpx.GPXTrack(
        name=_xml_text(track.name), description=_xml_text(track.description), number=track.number
    )
    written.type = _xml_text(track.kind)  # type: ignore[assignment]  # gpxpy declares this text field as always None
    segment = gpxpy.gpx.GPXTrackSegment()
    segment.points = [_track_point(point) for point in track.points]
    written.segments.append(segment)
    return written


def _track_point(point: TrackPoint) -> gpxpy.gpx.GPXTrackPoint:
    return gpxpy.gpx.GPXTrackPoint(
        latitude=_at_six_decimals(point.coordinate.latitude),
        longitude=_at_six_decimals(point.coordinate.longitude),
        elevation=_elevation(point.elevation_m),
    )


def _elevation(elevation_m: float | None) -> float | None:
    if elevation_m is None or not math.isfinite(elevation_m):
        return None
    return _at_six_decimals(elevation_m)


def _at_six_decimals(number: float) -> float:
    return round(number, DECIMAL_PLACES)


def _xml_text(text: str | None) -> str | None:
    return _FORBIDDEN_IN_XML.sub("", text or "") or None


def _holds_only_written_elements(root: Element) -> bool:
    return {element.tag for element in root.iter()} <= _WRITTEN_ELEMENTS


def _numbers_are_plain_decimals(root: Element) -> bool:
    numbers = [number for point in _raw_points_of(root) for number in point if number is not None]
    return all(_PLAIN_DECIMAL.fullmatch(number) for number in numbers)


def _points_of(root: Element) -> tuple[tuple[Decimal, Decimal, Decimal | None], ...]:
    return tuple(
        (Decimal(latitude), Decimal(longitude), None if elevation is None else Decimal(elevation))
        for latitude, longitude, elevation in _raw_points_of(root)
    )


def _raw_points_of(root: Element) -> list[tuple[str, str, str | None]]:
    return [
        (point.attrib["lat"], point.attrib["lon"], point.findtext(f"{_NS}ele"))
        for point in root.iter()
        if point.tag in _LOCATED_ELEMENTS
    ]


def _names_of(root: Element) -> tuple[str | None, ...]:
    return tuple(name.text for name in root.iter(f"{_NS}name"))

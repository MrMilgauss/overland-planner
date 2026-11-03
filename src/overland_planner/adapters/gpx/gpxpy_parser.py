"""`TrackFileParser` adapter (brief §6 and §12, ADR-010): defusedxml pre-parse, then gpxpy.

The pre-parse forbids DTDs, entities and external references, so gpxpy only ever reads plain XML; empty and
non-XML files fail there too. Anything gpxpy or the coordinate range check refuses is an invalid file as well,
never an error escaping to the caller.

First usable track (01a, user decision 2026-11-02; multi-track and multi-file rules are slice 07, D149): the first
`<trk>` holding a `<trkseg>` with at least two points; its points are those of that first such segment, in recorded
order (HC-1). Segments are never joined, so no straight line is invented across a recording gap. Name: the track's
`<name>`, else the file stem; its `<desc>` is carried through (D152).

Start-up probe (fatal, component `gpx_parser`): the embedded GPX must parse and the embedded billion-laughs sample
must be refused.
"""

from __future__ import annotations

from pathlib import PurePath
from xml.etree.ElementTree import ParseError

import defusedxml.ElementTree as safe_xml
import gpxpy
import gpxpy.gpx
from defusedxml import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden

from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.track_file_parser import (
    InvalidTrackFile,
    NoUsableTrack,
    ParsedTrack,
    TrackFileOutcome,
)
from overland_planner.domain.catalog.track import TrackPoint

MINIMUM_POINTS = 2

EMBEDDED_GPX = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<gpx version="1.1" creator="overland-planner probe" xmlns="http://www.topografix.com/GPX/1/1">'
    b'<trk><name>probe</name><trkseg><trkpt lat="45.056" lon="7.041"/><trkpt lat="44.958" lon="6.879"/>'
    b"</trkseg></trk></gpx>"
)
BILLION_LAUGHS = (
    b'<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY lol "lol">'
    b'<!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    b'<!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">'
    b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>'
    b'<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>&lol3;</name><trkseg>'
    b'<trkpt lat="45.0" lon="7.0"/><trkpt lat="45.1" lon="7.1"/></trkseg></trk></gpx>'
)

_FORBIDDEN = {
    DTDForbidden: "dtd_forbidden",
    EntitiesForbidden: "entities_forbidden",
    ExternalReferenceForbidden: "external_reference_forbidden",
}


class GpxpyParser:
    def __init__(self, sample: bytes = EMBEDDED_GPX, attack_sample: bytes = BILLION_LAUGHS) -> None:
        self._sample = sample
        self._attack_sample = attack_sample

    def parse(self, content: bytes, file_name: str) -> TrackFileOutcome:
        refusal = self._pre_parse_refusal(content)
        if refusal is not None:
            return InvalidTrackFile(file_name, refusal)
        try:
            return self._first_usable_track(gpxpy.parse(content), file_name)
        except (gpxpy.gpx.GPXException, ValueError):  # malformed values, out-of-range coordinates
            return InvalidTrackFile(file_name, "not_gpx")

    def probe(self) -> ProbeResult:
        if not isinstance(self.parse(self._sample, "probe.gpx"), ParsedTrack):
            return ProbeResult(outcome="fatal", reason="gpx_parser_sample_rejected")
        if not isinstance(self.parse(self._attack_sample, "probe.gpx"), InvalidTrackFile):
            return ProbeResult(outcome="fatal", reason="gpx_parser_accepted_entities")
        return ProbeResult(outcome="ok")

    @staticmethod
    def _pre_parse_refusal(content: bytes) -> str | None:
        try:
            safe_xml.fromstring(content, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        except (DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden) as forbidden:
            return _FORBIDDEN[type(forbidden)]
        except (ParseError, ValueError):
            return "not_xml"
        return None

    @staticmethod
    def _first_usable_track(gpx: gpxpy.gpx.GPX, file_name: str) -> TrackFileOutcome:
        for track in gpx.tracks:
            for segment in track.segments:
                if len(segment.points) >= MINIMUM_POINTS:
                    points = tuple(TrackPoint.at(p.latitude, p.longitude, p.elevation) for p in segment.points)
                    return ParsedTrack(track.name or PurePath(file_name).stem, track.description, points)
        return NoUsableTrack(file_name)

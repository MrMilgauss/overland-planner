"""Track file parser port (brief §6 and §12, ADR-010, US-02a): an uploaded file becomes one recorded track.

`parse(content, file_name)` answers one of three typed outcomes:
- `ParsedTrack`: the file's first usable track - its name (or the file stem when it has none), its description
  and its points in recorded order (HC-1);
- `InvalidTrackFile`: not a GPX file the planner accepts - empty, not XML, a DTD, entities or external
  references, or values the GPX reader refuses (e.g. malformed or out-of-range coordinates);
- `NoUsableTrack`: valid GPX, but no track has at least two points.

Its start-up probe parses an embedded GPX and must reject an embedded billion-laughs sample; any failure is fatal
(component `gpx_parser`). Production adapter: `adapters/gpx/gpxpy_parser.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from overland_planner.application.ports.probe import Probeable
from overland_planner.domain.catalog.track import TrackPoint


@dataclass(frozen=True)
class ParsedTrack:
    name: str
    description: str | None
    points: tuple[TrackPoint, ...]


@dataclass(frozen=True)
class InvalidTrackFile:
    file_name: str
    reason: str


@dataclass(frozen=True)
class NoUsableTrack:
    file_name: str


TrackFileOutcome = ParsedTrack | InvalidTrackFile | NoUsableTrack


class TrackFileParser(Probeable, Protocol):
    def parse(self, content: bytes, file_name: str) -> TrackFileOutcome: ...

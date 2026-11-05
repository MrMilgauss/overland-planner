"""GPX writer port (brief §6, ADR-010): a plain GPX document becomes GPX 1.1 bytes.

`write(document)` keeps every waypoint, track and point in the given order (HC-1) and adds no extensions and no foreign
elements; the same document always gives the same bytes. Its start-up probe writes an embedded document and re-parses
it; any failure is fatal (component `gpx_writer`). Production adapter: `adapters/gpx/gpxpy_writer.py`.
"""

from __future__ import annotations

from typing import Protocol

from overland_planner.application.ports.probe import Probeable
from overland_planner.domain.export.gpx_document import GpxDocument


class GpxWriter(Probeable, Protocol):
    def write(self, document: GpxDocument) -> bytes: ...

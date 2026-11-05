"""GPX export use case (brief §5, ADR-009 Amendment 2, ADR-010 Amendment 1, HC-1): a stored run becomes a GPX file.

Each track holds the canonical points of the run's own direction version, 1:1 in stored order, after its bytes are
proven against the hash the run recorded. A track that cannot be proven refuses the whole file and logs one
`invariant.violation`. Exporting reads only: no project, item or plan run changes. Slice 01b, tracks only so far.
"""

from __future__ import annotations

import hashlib

from overland_planner.application.catalog.facade import InvalidCanonicalPointsFileError, parse_canonical_points_file
from overland_planner.application.planning.facade import PlanRunQueries
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.file_store import CanonicalPointsMissing, FileStore
from overland_planner.application.ports.gpx_writer import GpxWriter
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.export.gpx_document import GpxDocument, GpxTrack
from overland_planner.domain.planning.plan_run import PlanStop

_INCONSISTENT_MESSAGE = "Track data for this run is inconsistent - recalculate"
_CHECK = "HC-5"  # the guard's rule for a track's full-sequence hash


class PlanRunNotFoundError(LookupError):
    """No plan run has this id."""


class TrackDataInconsistentError(ValueError):
    """A track's stored points are not the ones the run recorded; no file is made (ADR-009 Amendment 2)."""

    def __init__(self) -> None:
        super().__init__(_INCONSISTENT_MESSAGE)


class GpxExportService:
    def __init__(self, runs: PlanRunQueries, files: FileStore, writer: GpxWriter, event_log: EventLog) -> None:
        self._runs = runs
        self._files = files
        self._writer = writer
        self._event_log = event_log

    def export(self, plan_run_id: str) -> bytes:
        """The run's GPX file. Raises `PlanRunNotFoundError` or `TrackDataInconsistentError`."""
        run = self._runs.get(plan_run_id)
        if run is None:
            raise PlanRunNotFoundError(plan_run_id)
        tracks = tuple(
            GpxTrack(name=stop.name, points=self._stored_points(plan_run_id, stop))
            for stop in run.stops
            if stop.kind == "track"
        )
        return self._writer.write(GpxDocument(tracks=tracks))

    def _stored_points(self, plan_run_id: str, stop: PlanStop) -> tuple[TrackPoint, ...]:
        """The points of the run's direction version, or a refusal that names what is wrong with them."""
        version = stop.direction_version
        if version is None:
            raise self._refusal(plan_run_id, f"track {stop.item_id}: the stop names no direction version")
        content = self._files.read_canonical_points(stop.item_id, version)
        file = f"track {stop.item_id}: canonical file v{version}"
        if isinstance(content, CanonicalPointsMissing):
            raise self._refusal(plan_run_id, f"{file} is missing")
        if hashlib.sha256(content).hexdigest() != stop.canonical_sha256:
            raise self._refusal(plan_run_id, f"{file} has changed")
        try:
            return parse_canonical_points_file(content)
        except InvalidCanonicalPointsFileError as error:
            raise self._refusal(plan_run_id, f"{file} cannot be read") from error

    def _refusal(self, plan_run_id: str, detail: str) -> TrackDataInconsistentError:
        self._event_log.warning("invariant.violation", plan_run_id=plan_run_id, check=_CHECK, detail=detail)
        return TrackDataInconsistentError()

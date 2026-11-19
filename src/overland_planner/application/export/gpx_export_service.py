"""GPX export use case (brief §5, ADR-009 Amendment 2, ADR-010 Amendment 1, HC-1): a stored run becomes a named file.

Each trail holds the canonical points of the run's own direction version, 1:1 in stored order, after its bytes are
proven against the hash the run recorded; a retrace is proven against the hash of its track's points reversed. A track
that cannot be proven refuses the whole file and logs one `invariant.violation`; a Failed run is refused before
anything is read (D203). Road legs come from the stored itinerary, with no provider call. Exporting reads only: no
project, item or plan run changes. Each file logs one `export.gpx`; `stale` stays false until slice 04.
"""

from __future__ import annotations

from dataclasses import dataclass

from overland_planner.application.catalog.facade import (
    InvalidCanonicalPointsFileError,
    ProjectService,
    canonical_file_sha256,
    parse_canonical_points_file,
    reversed_points_sha256,
)
from overland_planner.application.planning.facade import PlanRunNotFoundError, PlanRunQueries
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.file_store import CanonicalPointsMissing, FileStore
from overland_planner.application.ports.gpx_writer import GpxWriter
from overland_planner.application.ports.plan_run_repository import PlanRunDetail
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.export.gpx_document import GpxDocument
from overland_planner.domain.export.gpx_document_builder import GpxDocumentBuilder, StopWithoutPlaceError
from overland_planner.domain.export.run_file_name import run_file_name
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.routing.provider_label import is_estimate

_INCONSISTENT_MESSAGE = "Track data for this run is inconsistent - recalculate"
_FAILED_MESSAGE = "This plan run failed"
_CHECK = "HC-5"  # the guard's rule for a track's full-sequence hash


class TrackDataInconsistentError(ValueError):
    """A track's stored points are not the ones the run recorded; no file is made (ADR-009 Amendment 2)."""

    def __init__(self) -> None:
        super().__init__(_INCONSISTENT_MESSAGE)


class FailedRunExportError(ValueError):
    """A Failed run has no itinerary to export (US-18 S7, D203)."""

    def __init__(self) -> None:
        super().__init__(_FAILED_MESSAGE)


@dataclass(frozen=True)
class GpxFile:
    file_name: str
    content: bytes


class GpxExportService:
    def __init__(
        self, runs: PlanRunQueries, projects: ProjectService, files: FileStore, writer: GpxWriter, event_log: EventLog
    ) -> None:
        self._runs = runs
        self._projects = projects
        self._files = files
        self._writer = writer
        self._event_log = event_log

    def export(self, plan_run_id: str) -> GpxFile:
        """The run's named GPX file. Raises `PlanRunNotFoundError`, `FailedRunExportError` or
        `TrackDataInconsistentError`."""
        run = self._runs.get(plan_run_id)
        if run is None:
            raise PlanRunNotFoundError(plan_run_id)
        if run.status == "failed":
            raise FailedRunExportError()
        estimate = is_estimate(run.provider_id)
        content = self._writer.write(self._document_of(run, estimate))
        file_name = run_file_name(self._projects.open(run.project_id).name.value, run.number, estimate=estimate)
        self._event_log.info(
            "export.gpx",
            plan_run_id=run.id,
            project_id=run.project_id,
            items_included=len({stop.item_id for stop in run.stops}),
            bytes=len(content),
            stale=False,
        )
        return GpxFile(file_name, content)

    def _document_of(self, run: PlanRunDetail, estimate: bool) -> GpxDocument:
        trail_points = {stop.item_id: self._stored_points(run.id, stop) for stop in run.stops if stop.kind == "track"}
        for stop in run.stops:
            if stop.kind == "retrace":
                self._prove_retrace(run.id, stop, trail_points.get(stop.item_id))
        try:
            return GpxDocumentBuilder(run.number, run.stops, trail_points, estimate).build()
        except StopWithoutPlaceError as error:
            raise self._refusal(run.id, str(error)) from error

    def _stored_points(self, plan_run_id: str, stop: PlanStop) -> tuple[TrackPoint, ...]:
        """The points of the run's direction version, or a refusal that names what is wrong with them."""
        version = stop.direction_version
        if version is None:
            raise self._refusal(plan_run_id, f"track {stop.item_id}: the stop names no direction version")
        content = self._files.read_canonical_points(stop.item_id, version)
        file = f"track {stop.item_id}: canonical file v{version}"
        if isinstance(content, CanonicalPointsMissing):
            raise self._refusal(plan_run_id, f"{file} is missing")
        if canonical_file_sha256(content) != stop.canonical_sha256:
            raise self._refusal(plan_run_id, f"{file} has changed")
        try:
            return parse_canonical_points_file(content)
        except InvalidCanonicalPointsFileError as error:
            raise self._refusal(plan_run_id, f"{file} cannot be read") from error

    def _prove_retrace(self, plan_run_id: str, stop: PlanStop, points: tuple[TrackPoint, ...] | None) -> None:
        """A retrace is written from its track's proven points, reversed, and only if they hash as the run recorded."""
        row = f"retrace of track {stop.item_id}"
        if points is None:
            raise self._refusal(plan_run_id, f"{row}: the run holds no such track")
        if reversed_points_sha256(points) != stop.retrace_sha256:
            raise self._refusal(plan_run_id, f"{row}: the points reversed have changed")

    def _refusal(self, plan_run_id: str, detail: str) -> TrackDataInconsistentError:
        self._event_log.warning("invariant.violation", plan_run_id=plan_run_id, check=_CHECK, detail=detail)
        return TrackDataInconsistentError()

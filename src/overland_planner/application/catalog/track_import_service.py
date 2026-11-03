"""Track import use case (brief §4, §9 and §12, ADR-018, US-02a, D149): uploaded GPX files become track items.

Several files in one request are all or nothing: every file is parsed first, and if any is refused nothing is
written. A file above the per-file upload cap (MAX_UPLOAD_FILE_MB, MB = MiB) is refused before anything is parsed.
For each accepted file the original is kept under its sha256 and the canonical points (direction version 1,
recorded order, HC-1) are written before the one database commit that adds the track items and
increments the project revision once. Each imported track logs `import.track` after the commit.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from overland_planner.application.catalog.project_service import existing_project
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.file_store import FileStore
from overland_planner.application.ports.repositories import CatalogUnitOfWork
from overland_planner.application.ports.track_file_parser import (
    InvalidTrackFile,
    NoUsableTrack,
    ParsedTrack,
    TrackFileParser,
)
from overland_planner.domain.catalog.item import TrackItem
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.catalog.track_stats_calculator import TrackStatsCalculator, UnusableTrack

FIRST_DIRECTION_VERSION = 1
MIB = 1024 * 1024  # MB in every upload cap (MAX_UPLOAD_*_MB) means MiB


@dataclass(frozen=True)
class TrackFile:
    """One uploaded file: its name as sent and its bytes."""

    name: str
    content: bytes


class TrackFilesRefusedError(ValueError):
    """At least one file of the import was refused; nothing was added. One message per refused file (D151).

    `too_large` = refused for the size cap, before any file was parsed (brief §5: 413 `upload_too_large`).
    """

    def __init__(self, messages: Sequence[str], *, too_large: bool = False) -> None:
        self.messages = tuple(messages)
        self.too_large = too_large
        super().__init__("; ".join(self.messages))


@dataclass(frozen=True)
class _Accepted:
    file: TrackFile
    track: ParsedTrack


class TrackImportService:
    def __init__(
        self,
        unit_of_work: Callable[[], CatalogUnitOfWork],
        parser: TrackFileParser,
        files: FileStore,
        event_log: EventLog,
        *,
        file_limit_mb: int,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._parser = parser
        self._files = files
        self._event_log = event_log
        self._stats = TrackStatsCalculator()
        self._file_limit_mb = file_limit_mb

    def import_files(self, project_id: str, uploads: Sequence[TrackFile]) -> list[TrackItem]:
        """Raises `ProjectNotFoundError` or `TrackFilesRefusedError`; in both cases nothing is added."""
        self._refuse_oversized(uploads)
        accepted = self._parse_all(uploads)
        with self._unit_of_work() as uow:
            project = existing_project(uow, project_id)
            items = [self._keep_files(project_id, upload) for upload in accepted]
            for item in items:
                uow.items.add(item)
            uow.projects.update(project.revised())
            uow.commit()
        for item in items:
            self._event_log.info(
                "import.track",
                project_id=project_id,
                track_id=item.id,
                point_count=item.point_count,
                length_m=round(item.length_m, 1),
                original_sha256=item.original_sha256,
            )
        return items

    def _refuse_oversized(self, uploads: Sequence[TrackFile]) -> None:
        limit = self._file_limit_mb * MIB
        oversized = [
            f"{u.name} is larger than the {self._file_limit_mb} MB limit" for u in uploads if len(u.content) > limit
        ]
        if oversized:
            raise TrackFilesRefusedError(oversized, too_large=True)

    def _parse_all(self, uploads: Sequence[TrackFile]) -> list[_Accepted]:
        accepted: list[_Accepted] = []
        refusals: list[str] = []
        for upload in uploads:
            outcome = self._parser.parse(upload.content, upload.name)
            if isinstance(outcome, InvalidTrackFile):
                refusals.append(f"{upload.name} is not a valid GPX file")
            elif isinstance(outcome, NoUsableTrack):
                refusals.append(f"{upload.name} has no usable track")
            else:
                accepted.append(_Accepted(upload, outcome))
        if refusals:
            raise TrackFilesRefusedError(refusals)
        return accepted

    def _keep_files(self, project_id: str, upload: _Accepted) -> TrackItem:
        stats = self._stats.calculate(upload.track.points)
        if isinstance(stats, UnusableTrack):  # the parser already refuses these; never trust it silently
            raise TrackFilesRefusedError([f"{upload.file.name} has no usable track"])
        track_id = uuid.uuid4().hex
        original_sha256 = _sha256(upload.file.content)
        canonical = canonical_points_file(upload.track.points)
        self._files.keep_original(original_sha256, upload.file.content)
        self._files.keep_canonical_points(track_id, FIRST_DIRECTION_VERSION, canonical)
        return TrackItem(
            id=track_id,
            project_id=project_id,
            name=upload.track.name,
            description=upload.track.description,
            original_sha256=original_sha256,
            canonical_sha256=_sha256(canonical),
            direction_version=FIRST_DIRECTION_VERSION,
            point_count=len(upload.track.points),
            entry=stats.entry.coordinate,
            exit=stats.exit.coordinate,
            length_m=stats.length_m,
        )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_points_file(points: Sequence[TrackPoint]) -> bytes:
    """`{"points": [[lat, lon, elevation_m|null], ...]}` in recorded order, compact UTF-8 JSON."""
    rows = [[p.coordinate.latitude, p.coordinate.longitude, p.elevation_m] for p in points]
    return json.dumps({"points": rows}, separators=(",", ":")).encode()

"""File store port (brief §4, §6 and §9, ADR-018): the planner's own files under `DATA_DIR`.

Layout: `files/originals/{sha256}.gpx` (uploads, byte-identical) and `files/tracks/{track_id}/canonical.v{n}.json`
(full-resolution points in the canonical order of direction version n). Every write is atomic: written and synced
under `DATA_DIR/tmp` (same filesystem), then renamed into place. Use cases write files before their database commit;
files are never deleted here (only the later orphan sweep removes unreferenced files).

Its start-up probe proves a file can be written, synced, renamed and read back under `DATA_DIR/tmp`; any failure is
fatal (component `file_store`). Production adapter: `adapters/files/local_file_store.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from overland_planner.application.ports.probe import Probeable


@dataclass(frozen=True)
class CanonicalPointsMissing:
    """The canonical points file of a track version is not there: an outcome the guard judges, not a crash."""


class FileStore(Probeable, Protocol):
    def keep_original(self, sha256: str, content: bytes) -> None:
        """Keep an uploaded file under its content hash; an original already kept is left as it is."""
        ...

    def keep_canonical_points(self, track_id: str, direction_version: int, content: bytes) -> None:
        """Keep a track's canonical points file of the given direction version."""
        ...

    def read_canonical_points(self, track_id: str, direction_version: int) -> bytes | CanonicalPointsMissing:
        """The bytes of a track's canonical points file of the given direction version, exactly as stored."""
        ...

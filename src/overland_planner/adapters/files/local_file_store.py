"""`FileStore` adapter: the planner's files under `DATA_DIR` (brief §4 and §6, ADR-011).

Start-up probe: write `DATA_DIR/tmp/probe-<uuid>.part`, fsync it, rename it to `probe-<uuid>`, fsync the folder,
read it back and delete it. Any failure is fatal; the reason names the step that failed.

Writes (ADR-018): every file is written and fsynced as `DATA_DIR/tmp/<uuid>.part` (the same filesystem as
`DATA_DIR/files`), renamed into place with `os.replace` and its folder fsynced, so a reader never sees half a file.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from pathlib import Path

from overland_planner.application.ports.probe import ProbeCheck, ProbeResult, first_failure


class LocalFileStore:
    def __init__(self, data_dir: Path) -> None:
        self._scratch = data_dir / "tmp"
        self._files = data_dir / "files"

    def keep_original(self, sha256: str, content: bytes) -> None:
        target = self._files / "originals" / f"{sha256}.gpx"
        if not target.exists():
            self._write_atomically(target, content)

    def keep_canonical_points(self, track_id: str, direction_version: int, content: bytes) -> None:
        self._write_atomically(self._files / "tracks" / track_id / f"canonical.v{direction_version}.json", content)

    def _write_atomically(self, target: Path, content: bytes) -> None:
        written = self._scratch / f"{uuid.uuid4().hex}.part"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._write_synced(written, content)
            self._rename_synced(written, target)
        finally:
            written.unlink(missing_ok=True)

    def probe(self) -> ProbeResult:
        name = f"probe-{uuid.uuid4().hex}"
        written, final = self._scratch / f"{name}.part", self._scratch / name
        content = name.encode()
        steps = (
            ProbeCheck("file_store_not_writable", lambda: self._write_synced(written, content)),
            ProbeCheck("file_store_rename_failed", lambda: self._rename_synced(written, final)),
            ProbeCheck("file_store_read_back_failed", lambda: final.read_bytes() == content),
        )
        try:
            return first_failure(steps, failing_errors=(OSError,))
        finally:
            for leftover in (written, final):
                with contextlib.suppress(OSError):
                    leftover.unlink(missing_ok=True)

    def _write_synced(self, file: Path, content: bytes) -> bool:
        self._scratch.mkdir(parents=True, exist_ok=True)
        with file.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return True

    @staticmethod
    def _rename_synced(source: Path, target: Path) -> bool:
        """Rename into place and fsync the target's folder, so the rename survives a power cut."""
        os.replace(source, target)
        _fsync_folder(target.parent)
        return True


def _fsync_folder(path: Path) -> None:
    folder = os.open(path, os.O_RDONLY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)

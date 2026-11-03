"""`FileStore` adapter: the planner's files under `DATA_DIR` (brief §4 and §6, ADR-011).

Start-up probe: write `DATA_DIR/tmp/probe-<uuid>.part`, fsync it, rename it to `probe-<uuid>`, fsync the folder,
read it back and delete it. Any failure is fatal; the reason names the step that failed.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Callable
from pathlib import Path

from overland_planner.application.ports.probe import ProbeResult


class LocalFileStore:
    def __init__(self, data_dir: Path) -> None:
        self._scratch = data_dir / "tmp"

    def probe(self) -> ProbeResult:
        name = f"probe-{uuid.uuid4().hex}"
        written, final = self._scratch / f"{name}.part", self._scratch / name
        content = name.encode()
        steps: tuple[tuple[str, Callable[[], bool]], ...] = (
            ("file_store_not_writable", lambda: self._write_synced(written, content)),
            ("file_store_rename_failed", lambda: self._rename_synced(written, final)),
            ("file_store_read_back_failed", lambda: final.read_bytes() == content),
        )
        try:
            for reason, step in steps:
                try:
                    passed = step()
                except OSError:
                    passed = False
                if not passed:
                    return ProbeResult(outcome="fatal", reason=reason)
            return ProbeResult(outcome="ok")
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

    def _rename_synced(self, source: Path, target: Path) -> bool:
        os.replace(source, target)
        folder = os.open(self._scratch, os.O_RDONLY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
        return True

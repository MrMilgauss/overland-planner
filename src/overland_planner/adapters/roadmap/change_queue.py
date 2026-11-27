"""RoadMapChanges on the changes folder (D303, D310, D315): the planner's two files, `request.txt` and `cancelled.txt`.

A request is written to a temporary file in the same folder, flushed to disk and renamed over `request.txt`, so the
helper never sees half of it. Cancelling is a rename of `request.txt` to `cancelled.txt` (never a delete): the helper's
own take is a rename of the same file, so the atomic rename decides who wins. Every other file of the folder is the
helper's and is never touched. The format is fixed lines; nothing is evaluated.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.road_map_changes import (
    ChangeRequest,
    ChangesUnavailableError,
    RequestedRegion,
)

REQUEST = "request.txt"
CANCELLED = "cancelled.txt"
UNAVAILABLE = ProbeResult(outcome="degraded-healthy", reason="road_map_changes_unavailable")
_MAX_BYTES = 1_000_000
_FIELDS = 6  # key, name, parent name, pbf address, poly address, bytes


class ChangeQueueDir:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def available(self) -> bool:
        return self._directory.is_dir() and os.access(self._directory, os.W_OK | os.X_OK)

    def queue(self, request: ChangeRequest, added: Sequence[str], removed: Sequence[str]) -> None:
        text = _text_of(request, added, removed)
        try:
            handle, temporary = tempfile.mkstemp(dir=self._directory, prefix=".request-", suffix=".tmp")
        except OSError as unwritable:
            raise ChangesUnavailableError(str(unwritable)) from unwritable
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as written:
                os.fchmod(handle, 0o644)  # the helper runs as another user
                written.write(text)
                written.flush()
                os.fsync(written.fileno())
            os.replace(temporary, self._directory / REQUEST)
        except OSError as unwritable:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise ChangesUnavailableError(str(unwritable)) from unwritable
        _sync_folder(self._directory)

    def cancel(self) -> bool:
        try:
            os.rename(self._directory / REQUEST, self._directory / CANCELLED)
        except FileNotFoundError:
            return False
        except OSError as unwritable:
            raise ChangesUnavailableError(str(unwritable)) from unwritable
        return True

    def pending(self) -> ChangeRequest | None:
        try:
            path = self._directory / REQUEST
            if path.stat().st_size > _MAX_BYTES:
                return None
            return _request_of(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return None

    def probe(self) -> ProbeResult:
        try:
            self._round_trip()
        except OSError:
            return UNAVAILABLE
        return ProbeResult(outcome="ok")

    def _round_trip(self) -> None:
        """Write, flush, rename, read back and delete one probe file: what a request goes through."""
        token = secrets.token_hex(8)
        first, second = (self._directory / f".probe-{token}.{ending}" for ending in ("tmp", "txt"))
        try:
            descriptor = os.open(first, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(descriptor, "w", encoding="utf-8") as written:
                written.write(token)
                written.flush()
                os.fsync(written.fileno())
            os.replace(first, second)
            if second.read_text(encoding="utf-8") != token:
                raise OSError("the probe file reads back differently")
        finally:
            for leftover in (first, second):
                with contextlib.suppress(OSError):
                    os.unlink(leftover)


def _sync_folder(directory: Path) -> None:
    with contextlib.suppress(OSError):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _text_of(request: ChangeRequest, added: Sequence[str], removed: Sequence[str]) -> str:
    lines = ["schema=1", f"requested_at={int(request.requested_at.timestamp())}"]
    if request.start_at is not None:
        lines.append(f"start_at={int(request.start_at.timestamp())}")
    for region in request.regions:
        fields = (
            region.key,
            region.name,
            region.parent_name or "",
            region.pbf_url,
            region.poly_url,
            str(region.bytes),
        )
        lines.append("region=" + "\t".join(fields))
    lines += [f"added={', '.join(added)}", f"removed={', '.join(removed)}"]
    return "\n".join(lines) + "\n"


def _request_of(text: str) -> ChangeRequest:
    lines = text.splitlines()
    if not lines or lines[0] != "schema=1":
        raise ValueError("not a schema 1 request")
    values = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in lines[1:] if "=" in line}
    start = values.get("start_at")
    regions = tuple(_region_of(line.split("=", 1)[1]) for line in lines if line.startswith("region="))
    return ChangeRequest(
        requested_at=datetime.fromtimestamp(int(values["requested_at"]), UTC),
        start_at=None if start is None else datetime.fromtimestamp(int(start), UTC),
        regions=regions,
    )


def _region_of(line: str) -> RequestedRegion:
    fields = line.split("\t")
    if len(fields) != _FIELDS:
        raise ValueError("a region line holds six fields")
    key, name, parent, pbf_url, poly_url, size = fields
    return RequestedRegion(key, name, parent or None, pbf_url, poly_url, int(size))

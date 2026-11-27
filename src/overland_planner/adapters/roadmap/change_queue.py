"""RoadMapChanges on the changes folder (D303, D310, D315): the planner's two files, `request.txt` and `cancelled.txt`.

A request is written to a temporary file in the same folder, flushed to disk and renamed over `request.txt`, so the
helper never sees half of it. Cancelling is a rename of `request.txt` to `cancelled.txt` (never a delete): the helper's
own take is a rename of the same file, so the atomic rename decides who wins. Every other file of the folder is the
helper's and is never touched. The format is fixed lines; nothing is evaluated.
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import stat
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.road_map_changes import (
    STEPS,
    ChangeRequest,
    ChangesUnavailableError,
    RebuildProgress,
    RebuildResult,
    RequestedRegion,
)

REQUEST = "request.txt"
CANCELLED = "cancelled.txt"
RUNNING = "running.txt"
PROGRESS = "progress.txt"
HELPER_SEEN = "helper-seen"
RESULT = "result.txt"
PREVIOUS_RESULT = "previous-result.txt"
UNAVAILABLE = ProbeResult(outcome="degraded-healthy", reason="road_map_changes_unavailable")
_MAX_BYTES = 1_000_000
_MAX_NOTE_BYTES = 4096  # the helper's notes are a few short lines
_PROGRESS_KEYS = frozenset({"step", "step_at", "serving", "new"})
_REQUEST_KEYS = frozenset({"schema", "requested_at", "start_at", "added", "removed"})  # and `region`, which repeats
_RESULT_KEYS = frozenset({"finished_at", "state", "code", "free_gb", "need_gb", "have_gb", "tileset"})
_CODE = re.compile(r"[a-z_]{1,32}")
_TILESET = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_NUMBER = re.compile(r"\d{1,6}")
_EPOCH = re.compile(r"\d{1,12}")
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
            self._start_afresh()
            os.replace(temporary, self._directory / REQUEST)
        except OSError as unwritable:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise ChangesUnavailableError(str(unwritable)) from unwritable
        _sync_folder(self._directory)

    def waiting(self) -> bool:
        return (self._directory / REQUEST).exists()

    def running(self) -> bool:
        return (self._directory / RUNNING).exists()

    def _start_afresh(self) -> None:
        """A new request: the last result is kept as the previous one, a cancel is forgotten."""
        with contextlib.suppress(FileNotFoundError):
            os.replace(self._directory / RESULT, self._directory / PREVIOUS_RESULT)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._directory / CANCELLED)

    def cancel(self) -> bool:
        try:
            os.rename(self._directory / REQUEST, self._directory / CANCELLED)
        except FileNotFoundError:
            return False
        except OSError as unwritable:
            raise ChangesUnavailableError(str(unwritable)) from unwritable
        return True

    def pending(self) -> ChangeRequest | None:
        return self._request_in(REQUEST)

    def running_request(self) -> ChangeRequest | None:
        return self._request_in(RUNNING)

    def progress(self) -> RebuildProgress | None:
        values = _note_of(self._directory / PROGRESS, _PROGRESS_KEYS)
        try:
            step, step_at = values["step"], int(values["step_at"])
            return RebuildProgress(step, datetime.fromtimestamp(step_at, UTC)) if step in STEPS else None
        except (KeyError, ValueError, OverflowError, OSError):
            return None

    def result(self) -> RebuildResult | None:
        raw = _read_note(self._directory / RESULT)
        if raw is None:
            return None
        try:
            return _result_of(raw)
        except (ValueError, OverflowError, OSError):
            return None

    def helper_seen_at(self) -> datetime | None:
        try:
            found = (self._directory / HELPER_SEEN).lstat()
        except OSError:
            return None
        return datetime.fromtimestamp(found.st_mtime, UTC) if stat.S_ISREG(found.st_mode) else None

    def _request_in(self, name: str) -> ChangeRequest | None:
        try:
            path = self._directory / name
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


def _read_note(path: Path) -> str | None:
    """The text of a helper's note: a plain file of at most 4 KB, else None."""
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return None
        with path.open("rb") as note:
            raw = note.read(_MAX_NOTE_BYTES + 1)
        return None if len(raw) > _MAX_NOTE_BYTES else raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _result_of(text: str) -> RebuildResult | None:
    """The result as the request lines the helper copied plus its own known keys, each once; anything else: None."""
    lines = [line for line in text.splitlines() if line]
    if not all("=" in line for line in lines):
        return None
    keys = [line.split("=", 1)[0] for line in lines]
    singles = [key for key in keys if key != "region"]
    known = _REQUEST_KEYS | _RESULT_KEYS
    if len(set(singles)) != len(singles) or not set(singles) <= known:
        return None
    values = {key: value for key, value in (line.split("=", 1) for line in lines) if key != "region"}
    state, code, tileset = values.get("state"), values.get("code"), values.get("tileset")
    numbers = {key: values.get(key) for key in ("free_gb", "need_gb", "have_gb")}
    if (
        state not in ("done", "failed")
        or not _EPOCH.fullmatch(values.get("finished_at", ""))
        or (code is not None and not _CODE.fullmatch(code))
        or (tileset is not None and not _TILESET.fullmatch(tileset))
        or any(number is not None and not _NUMBER.fullmatch(number) for number in numbers.values())
    ):
        return None
    request_text = "\n".join(line for line in lines if line.split("=", 1)[0] in {*_REQUEST_KEYS, "region"})
    try:
        request: ChangeRequest | None = _request_of(request_text + "\n")
    except (ValueError, KeyError):
        request = None
    return RebuildResult(
        state=state,
        finished_at=datetime.fromtimestamp(int(values["finished_at"]), UTC),
        code=code,
        free_gb=None if numbers["free_gb"] is None else int(numbers["free_gb"]),
        need_gb=None if numbers["need_gb"] is None else int(numbers["need_gb"]),
        have_gb=None if numbers["have_gb"] is None else int(numbers["have_gb"]),
        tileset=tileset,
        request=request,
        added=_names_of(values.get("added")),
        removed=_names_of(values.get("removed")),
    )


def _names_of(line: str | None) -> tuple[str, ...]:
    return tuple(name for name in (line or "").split(", ") if name)


def _note_of(path: Path, keys: frozenset[str]) -> dict[str, str]:
    """The helper's note as `key=value` lines. A file that is not a plain file, is over 4 KB, repeats a key or holds a
    key not in `keys` says nothing at all ({}): the planner never trusts half of it."""
    text = _read_note(path)
    if text is None:
        return {}
    pairs = [line.split("=", 1) for line in text.splitlines() if line]
    values = dict(pairs) if all(len(pair) == 2 for pair in pairs) else {}
    return values if len(values) == len(pairs) and values.keys() <= keys else {}


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

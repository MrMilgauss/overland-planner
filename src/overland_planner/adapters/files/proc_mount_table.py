"""`MountTable` adapter over /proc/self/mountinfo (ADR-011 amendment D121, brief §6).

Each mountinfo line is `id parent major:minor root mount_point options [optional fields...] - fstype source opts`;
the mount point (field 5) escapes space, tab, newline and backslash as octal (`\\040`, `\\011`, `\\012`, `\\134`).
A host without the file outside Linux (macOS) has no mount table: `entries()` is None and the probe not_applicable.
On Linux a missing, unreadable or unparsable file raises `MountTableUnreadableError`; the probe then reports
degraded-healthy `data_dir_persistence_unknown`, as it does for a table without a `/` entry.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from overland_planner.application.ports.host import MountEntry, MountTableUnreadableError
from overland_planner.application.ports.probe import ProbeResult

MOUNTINFO = Path("/proc/self/mountinfo")
_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")
_SEPARATOR = " - "
_MOUNT_POINT_FIELD = 4
_MIN_LEADING_FIELDS = 6


def decode_mount_point(field: str) -> str:
    return _OCTAL_ESCAPE.sub(lambda escape: chr(int(escape[1], 8)), field)


def _parse_line(line: str) -> MountEntry:
    leading, separator, trailing = line.partition(_SEPARATOR)
    fields, filesystem = leading.split(" "), trailing.split(" ")
    if not separator or len(fields) < _MIN_LEADING_FIELDS or not filesystem[0]:
        raise MountTableUnreadableError(f"unparsable mountinfo line: {line!r}")
    return decode_mount_point(fields[_MOUNT_POINT_FIELD]), filesystem[0]


class ProcMountTable:
    def __init__(self, mountinfo: Path = MOUNTINFO, *, linux: bool = sys.platform.startswith("linux")) -> None:
        self._mountinfo = mountinfo
        self._linux = linux

    def entries(self) -> list[MountEntry] | None:
        if not self._linux and not self._mountinfo.exists():
            return None
        try:
            text = self._mountinfo.read_bytes().decode("utf-8", errors="surrogateescape")  # no newline translation
        except OSError as unreadable:
            raise MountTableUnreadableError(str(unreadable)) from unreadable
        return [_parse_line(line) for line in text.split("\n") if line]  # only \n ends a line

    def probe(self) -> ProbeResult:
        try:
            entries = self.entries()
        except MountTableUnreadableError:
            return ProbeResult(outcome="degraded-healthy", reason="data_dir_persistence_unknown")
        if entries is None:
            return ProbeResult(outcome="not_applicable")
        if not any(mount_point == "/" for mount_point, _ in entries):
            return ProbeResult(outcome="degraded-healthy", reason="data_dir_persistence_unknown")
        return ProbeResult(outcome="ok")

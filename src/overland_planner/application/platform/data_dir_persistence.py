"""Whether `DATA_DIR` survives a restart (ADR-011 amendment D121, brief §6 and §7, D168).

Pure classification over the host's mount table: the entry whose mount point is the longest component-wise prefix of
the resolved `DATA_DIR` decides (`/data2` is not under `/data`). The composition root resolves symlinks first.
- overlay, tmpfs, ramfs -> degraded-unhealthy: `/healthz` 503 with `NOT_PERSISTENT_MESSAGE`, home-page banner;
- any other filesystem type -> ok;
- no mount table on this host (macOS) -> not_applicable, healthy;
- a mount table that cannot be read or parsed, or one without a covering entry -> degraded-healthy
  `data_dir_persistence_unknown`.
When several entries share the deciding mount point (stacked mounts), any non-persistent one makes the folder
non-persistent, so the verdict does not depend on the order of the entries.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

from overland_planner.application.ports.host import MountEntry, MountTable, MountTableUnreadableError
from overland_planner.application.ports.probe import ProbeResult

NOT_PERSISTENT_MESSAGE = "Data directory is not persistent - projects would be lost on restart"
NON_PERSISTENT_FILESYSTEMS = frozenset({"overlay", "tmpfs", "ramfs"})
LOG_REASONS = {NOT_PERSISTENT_MESSAGE: "data_dir_not_persistent"}  # event-log codes of the banner reasons

OK = ProbeResult(outcome="ok")
NOT_APPLICABLE = ProbeResult(outcome="not_applicable")
NOT_PERSISTENT = ProbeResult(outcome="degraded-unhealthy", reason=NOT_PERSISTENT_MESSAGE)
UNKNOWN = ProbeResult(outcome="degraded-healthy", reason="data_dir_persistence_unknown")


def log_reason(reason: str | None) -> str | None:
    """The event-log code for a probe reason (the banner text of a non-persistent folder is logged as a code)."""
    return LOG_REASONS.get(reason or "", reason)


def classify_data_dir(data_dir: PurePosixPath, entries: Sequence[MountEntry] | None) -> ProbeResult:
    if entries is None:
        return NOT_APPLICABLE
    covering = [(PurePosixPath(mount), fstype) for mount, fstype in entries if data_dir.is_relative_to(mount)]
    if not covering:
        return UNKNOWN
    deepest = max(len(mount.parts) for mount, _ in covering)
    deciding = {fstype for mount, fstype in covering if len(mount.parts) == deepest}
    if deciding & NON_PERSISTENT_FILESYSTEMS:
        return NOT_PERSISTENT
    return OK


class DataDirPersistence:
    """The `data_dir` start-up component: classifies the resolved `DATA_DIR` against the host's mount table."""

    def __init__(self, data_dir: PurePosixPath, mount_table: MountTable) -> None:
        self._data_dir = data_dir
        self._mount_table = mount_table

    def probe(self) -> ProbeResult:
        try:
            entries = self._mount_table.entries()
        except MountTableUnreadableError:
            return UNKNOWN
        return classify_data_dir(self._data_dir, entries)

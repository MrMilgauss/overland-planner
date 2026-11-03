"""Host environment port: the host's mount table, for the `DATA_DIR` persistence probe (ADR-011 amendment D121).

The platform module classifies `DATA_DIR` by the filesystem type of the longest-prefix mount entry of the resolved
path (`application/platform/data_dir_persistence.py`). External, non-deterministic port (DISTILL D105):
`ProcMountTable` (/proc/self/mountinfo) in production, `FakeMountTable` in in-process tests via `ExternalPorts`.
"""

from __future__ import annotations

from typing import Protocol

from overland_planner.application.ports.probe import Probeable

MountEntry = tuple[str, str]  # (mount_point, fstype)


class MountTableUnreadableError(Exception):
    """The host has a mount table, but it cannot be read or parsed."""


class MountTable(Probeable, Protocol):
    def entries(self) -> list[MountEntry] | None:
        """Every mount point with its filesystem type; None when the host has no mount table (macOS).

        Raises `MountTableUnreadableError` when the host has one that cannot be read or parsed.
        """
        ...

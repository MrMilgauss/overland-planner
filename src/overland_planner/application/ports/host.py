"""Host environment port: the host's mount table, for the `DATA_DIR` persistence probe (ADR-011 amendment D121).

The composition root classifies `DATA_DIR` by the filesystem type of the longest-prefix mount entry of the resolved
path: overlay/tmpfs/ramfs -> degraded; any other -> ok; `entries()` is None (non-Linux) -> not_applicable.
External, non-deterministic port (DISTILL D105): `ProcMountTable` (/proc/self/mountinfo) in production,
`FakeMountTable` in in-process tests via `ExternalPorts`. RED scaffold (created by DISTILL): interface only.
"""

from __future__ import annotations

from typing import Protocol

from overland_planner.application.ports.probe import Probeable

__SCAFFOLD__ = True

MountEntry = tuple[str, str]  # (mount_point, fstype)


class MountTable(Probeable, Protocol):
    def entries(self) -> list[MountEntry] | None:
        """Every mount point with its filesystem type; None when the host has no mount table (macOS)."""
        ...

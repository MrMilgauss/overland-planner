"""Fakes for external / non-deterministic driven ports (docs/architecture/atdd-infrastructure-policy.md).

These are test doubles, not scaffolds: they are complete and honour the production port Protocols.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from overland_planner.application.ports.probe import ProbeResult


class FakeClock:
    """`Clock` port double: fixed UTC time that only moves when the test advances it."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 2, 19, 30, tzinfo=UTC)
        self._monotonic = 1_000.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


class FakeMountTable:
    """`MountTable` port double: a fixed list of (mount_point, fstype) entries.

    Default: `/` on ext4 (a persistent host disk). `FakeMountTable.with_mount(folder, "overlay")` adds a mount entry,
    e.g. to make `DATA_DIR` look like a container layer that would not survive a restart.
    """

    def __init__(self, entries: list[tuple[str, str]] | None = None) -> None:
        self._entries = list(entries) if entries is not None else [("/", "ext4")]

    @classmethod
    def with_mount(cls, folder: Path, fstype: str) -> FakeMountTable:
        return cls([("/", "ext4"), (str(folder.resolve()), fstype)])

    def entries(self) -> list[tuple[str, str]] | None:
        return list(self._entries)

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

"""Fakes for external / non-deterministic driven ports (docs/architecture/atdd-infrastructure-policy.md).

These are test doubles, not scaffolds: they are complete and honour the production port Protocols.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from overland_planner.application.ports.host import MountTableUnreadableError
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
    `FakeMountTable.unreadable()` stands for a Linux host whose mount table cannot be read or parsed,
    `FakeMountTable.absent()` for a host without a mount table (macOS).
    """

    def __init__(
        self, entries: list[tuple[str, str]] | None = None, *, readable: bool = True, present: bool = True
    ) -> None:
        self._entries = list(entries) if entries is not None else [("/", "ext4")]
        self._readable = readable
        self._present = present

    @classmethod
    def absent(cls) -> FakeMountTable:
        return cls(present=False)

    @classmethod
    def unreadable(cls) -> FakeMountTable:
        return cls(readable=False)

    @classmethod
    def with_mount(cls, folder: Path, fstype: str) -> FakeMountTable:
        return cls([("/", "ext4"), (str(folder.resolve()), fstype)])

    def entries(self) -> list[tuple[str, str]] | None:
        if not self._readable:
            raise MountTableUnreadableError("fake: mount table unreadable")
        return list(self._entries) if self._present else None

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

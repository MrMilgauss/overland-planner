"""Clock port (brief §6): `SystemClock` in production, `FakeClock` in tests."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from overland_planner.application.ports.probe import Probeable


class Clock(Probeable, Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware (UTC)."""
        ...

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin; never decreases."""
        ...

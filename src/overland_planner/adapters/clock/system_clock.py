"""`Clock` adapter backed by the host clock."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from overland_planner.application.ports.probe import ProbeResult


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

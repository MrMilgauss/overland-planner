"""HealthService (ADR-011, brief §5 and §7, D108): what the start-up probes mean for the planner's health.

The service holds the outcome of every registered component's start-up probe; `bootstrap/startup.py` probes each
component exactly once, in wiring order, before the app serves its first request. Components are reported in name
order, so the result does not depend on the order in which they were registered.

A component given in `reprobed` (the routing engine, D247) is probed again on demand (`probe(name)`, before each plan
request) and by `detail()` when its stored result is older than 60 s by the Clock port; every other component keeps its
start-up result. No background thread: a result is only ever refreshed by a call.

- `liveness()` (behind `/healthz`): unhealthy when any component is degraded-unhealthy or fatal; the reason is the
  first such component's reason.
- `detail()` (behind `/api/health`): every component's outcome, plus one banner per degraded-unhealthy component.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.probe import Probeable, ProbeOutcome, ProbeResult

HealthStatus = Literal["ok", "unhealthy"]

_UNHEALTHY: frozenset[ProbeOutcome] = frozenset({"degraded-unhealthy", "fatal"})
_STALE_AFTER_S = 60.0


@dataclass(frozen=True)
class Liveness:
    status: HealthStatus
    reason: str | None = None


@dataclass(frozen=True)
class HealthDetail:
    status: HealthStatus
    components: Mapping[str, ProbeResult]
    banners: tuple[str, ...]


class HealthService:
    def __init__(
        self,
        outcomes: Mapping[str, ProbeResult],
        *,
        clock: Clock | None = None,
        reprobed: Mapping[str, Probeable] | None = None,
    ) -> None:
        if reprobed and clock is None:
            raise ValueError("components probed again need the Clock port")
        self._clock = clock
        self._reprobed = dict(reprobed or {})
        self._current = {name: outcomes[name] for name in sorted(outcomes)}
        self._checked_at = {name: clock.monotonic() for name in self._reprobed} if clock else {}
        self._lock = threading.Lock()
        self._outcomes: Mapping[str, ProbeResult] = MappingProxyType(self._current)

    def probe(self, name: str) -> ProbeResult | None:
        """Probe the component now and keep its result; a component that is not probed again answers its start-up
        result (None when unknown)."""
        with self._lock:
            return self._probe_locked(name)

    def _probe_locked(self, name: str) -> ProbeResult | None:
        component = self._reprobed.get(name)
        if component is None or self._clock is None:
            return self._current.get(name)
        result = component.probe()
        self._current[name] = result
        self._checked_at[name] = self._clock.monotonic()
        return result

    def _refresh_stale(self) -> None:
        if self._clock is None:
            return
        with self._lock:
            for name in self._reprobed:
                if self._clock.monotonic() - self._checked_at[name] > _STALE_AFTER_S:
                    self._probe_locked(name)

    def liveness(self) -> Liveness:
        with self._lock:
            return self._liveness()

    def _liveness(self) -> Liveness:
        unhealthy = [result for result in self._outcomes.values() if result.outcome in _UNHEALTHY]
        if unhealthy:
            return Liveness("unhealthy", unhealthy[0].reason)
        return Liveness("ok")

    def detail(self) -> HealthDetail:
        self._refresh_stale()
        with self._lock:
            components = dict(self._outcomes)
            banners = tuple(
                result.reason
                for result in components.values()
                if result.outcome == "degraded-unhealthy" and result.reason is not None
            )
            return HealthDetail(self._liveness().status, components, banners)

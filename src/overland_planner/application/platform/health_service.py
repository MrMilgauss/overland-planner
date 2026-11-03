"""HealthService (ADR-011, brief §5 and §7, D108): what the start-up probes mean for the planner's health.

The service holds the outcome of every registered component's start-up probe; `bootstrap/startup.py` probes each
component exactly once, in wiring order, before the app serves its first request. Components are reported in name
order, so the result does not depend on the order in which they were registered.

- `liveness()` (behind `/healthz`): unhealthy when any component is degraded-unhealthy or fatal; the reason is the
  first such component's reason.
- `detail()` (behind `/api/health`): every component's outcome, plus one banner per degraded-unhealthy component.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from overland_planner.application.ports.probe import ProbeOutcome, ProbeResult

HealthStatus = Literal["ok", "unhealthy"]

_UNHEALTHY: frozenset[ProbeOutcome] = frozenset({"degraded-unhealthy", "fatal"})


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
    def __init__(self, outcomes: Mapping[str, ProbeResult]) -> None:
        self._outcomes = MappingProxyType({name: outcomes[name] for name in sorted(outcomes)})

    def liveness(self) -> Liveness:
        unhealthy = [result for result in self._outcomes.values() if result.outcome in _UNHEALTHY]
        if unhealthy:
            return Liveness("unhealthy", unhealthy[0].reason)
        return Liveness("ok")

    def detail(self) -> HealthDetail:
        banners = tuple(
            result.reason
            for result in self._outcomes.values()
            if result.outcome == "degraded-unhealthy" and result.reason is not None
        )
        return HealthDetail(self.liveness().status, self._outcomes, banners)

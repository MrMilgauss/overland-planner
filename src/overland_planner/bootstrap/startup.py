"""Start-up gate (brief §7, D190): a fatal component stops the start before the planner answers anything.

Components are probed in the order they were wired. The first fatal outcome stops probing, logs exactly one
`health.startup.refused` {component, reason} line and exits non-zero: `StartupRefusedError` is a `SystemExit`, so
`uvicorn --factory` ends with exit code 1 without printing anything on stdout. Invalid settings take the same path.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import NoReturn

from overland_planner.application.platform.facade import HealthService
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.probe import Probeable, ProbeResult

REFUSAL_EXIT_CODE = 1


class StartupRefusedError(SystemExit):
    def __init__(self, component: str, reason: str) -> None:
        super().__init__(REFUSAL_EXIT_CODE)
        self.component = component
        self.reason = reason


class StartupGate:
    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log

    def refuse(self, component: str, reason: str) -> NoReturn:
        self._event_log.info("health.startup.refused", component=component, reason=reason)
        raise StartupRefusedError(component, reason)

    def probe_in_order(
        self, components: Mapping[str, Probeable], *, clock: Clock | None = None, reprobed: Collection[str] = ()
    ) -> HealthService:
        """Probe each component once, in order; refuse at the first fatal one, else report every outcome.

        The components named in `reprobed` are the ones the health service probes again later (ADR-011, D247)."""
        outcomes: dict[str, ProbeResult] = {}
        for name, component in components.items():
            result = component.probe()
            if result.outcome == "fatal":
                self.refuse(name, result.reason or "fatal")
            outcomes[name] = result
        return HealthService(outcomes, clock=clock, reprobed={name: components[name] for name in reprobed})

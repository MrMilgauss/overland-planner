"""Start-up probing (brief §7): every registered component reports its outcome before the app serves traffic.

Fatal outcomes refuse the start (`health.startup.refused`) once the fatal adapters arrive (02-01).
"""

from __future__ import annotations

from overland_planner.application.platform.facade import HealthService
from overland_planner.bootstrap.registry import ProbeRegistry


def probe_every_component(registry: ProbeRegistry) -> HealthService:
    return HealthService.after_probing(registry.components())

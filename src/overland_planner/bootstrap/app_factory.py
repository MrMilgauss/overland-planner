"""Composition root (ADR-011 + Amendment 1): validate config -> wire -> migrate -> probe -> serve.

Production: `uvicorn --factory overland_planner.bootstrap.app_factory:create_app` (reads `os.environ`).
Acceptance tests: `create_app(environ, external=ExternalPorts(...))` with the same `.env` keys (brief §12)
and fakes only for external / non-deterministic ports (docs/architecture/atdd-infrastructure-policy.md).
Order: wire -> probe every registered component -> mount routes (API and health first, then the built web page,
D162) -> log `app.started`. uvicorn serves only once the factory returns, so no request is answered before every
component has reported its probe outcome; each degraded component gets one `health.startup.degraded` line
{component, reason} before `app.started`. The OR-Tools probe runs in a short-lived child process.
The database (02-01) and more probed adapters join in their slices.

stdout carries only the JSON event lines (brief §12): uvicorn's plain-text access log is switched off here, so the
production command needs no logging flags.
"""

from __future__ import annotations

import logging
import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass

from fastapi import FastAPI

from overland_planner.adapters.clock.system_clock import SystemClock
from overland_planner.adapters.http.platform_routes import platform_routes
from overland_planner.adapters.http.web_page import mount_web_page
from overland_planner.adapters.logging.structlog_event_log import StructlogEventLog
from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.host import MountTable
from overland_planner.application.ports.tour_solver import TourSolver
from overland_planner.bootstrap.probes import probe_every_component
from overland_planner.bootstrap.registry import ProbeRegistry
from overland_planner.bootstrap.settings import Settings


@dataclass(frozen=True)
class ExternalPorts:
    """Substitutes for external / non-deterministic driven ports. `None` = the production adapter.

    `tour_solver` exists only for the recorded waivers W1/W2 (atdd-infrastructure-policy.md).
    """

    clock: Clock | None = None
    mount_table: MountTable | None = None
    tour_solver: TourSolver | None = None


def create_app(
    environ: Mapping[str, str] | None = None,
    *,
    external: ExternalPorts | None = None,
) -> FastAPI:
    """Build the planner application. `environ=None` means `os.environ`; a mapping is the only source read."""
    settings = Settings.from_environ(os.environ if environ is None else environ)
    ports = external or ExternalPorts()
    clock = ports.clock or SystemClock()
    event_log: EventLog = StructlogEventLog(clock, app_version=settings.planner_git_sha)
    registry = ProbeRegistry()
    registry.register("clock", clock)
    registry.register("event_log", event_log)
    registry.register("tour_solver", ports.tour_solver or OrToolsTourSolver())
    health = probe_every_component(registry)
    for name, result in health.detail().components.items():
        if result.outcome.startswith("degraded"):
            event_log.info("health.startup.degraded", component=name, reason=result.reason)

    logging.getLogger("uvicorn.access").disabled = True
    app = FastAPI(title="Overland Route Planner", version=settings.planner_git_sha)
    app.include_router(platform_routes(health))
    mount_web_page(app, settings.web_dist_dir)
    event_log.info(
        "app.started",
        routing_provider=settings.routing_provider,
        solver_budget=settings.solver_budget,
        python_version=platform.python_version(),
    )
    return app

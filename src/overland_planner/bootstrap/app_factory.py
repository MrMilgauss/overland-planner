"""Composition root (ADR-011 + Amendment 1): validate config -> wire -> migrate -> probe -> serve.

Production: `uvicorn --factory overland_planner.bootstrap.app_factory:create_app` (reads `os.environ`).
Acceptance tests: `create_app(environ, external=ExternalPorts(...))` with the same `.env` keys (brief §12)
and fakes only for external / non-deterministic ports (docs/architecture/atdd-infrastructure-policy.md).
Order: settings -> wire -> probe every registered component in wiring order (the database probe migrates it to head
first) -> mount routes (API and health first, then the built web page, D162) -> log `app.started`. uvicorn serves only
once the factory returns, so no request is answered before every component has reported its probe outcome. Invalid
settings or the first fatal component refuse the start (`bootstrap/startup.py`: one `health.startup.refused` line,
exit non-zero, no `app.started`); each degraded component gets one `health.startup.degraded` line {component, reason}
before `app.started`. The OR-Tools probe runs in a short-lived child process.

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
from overland_planner.adapters.http.catalog_routes import catalog_routes
from overland_planner.adapters.http.errors import install_error_handlers
from overland_planner.adapters.http.platform_routes import platform_routes
from overland_planner.adapters.http.web_page import mount_web_page
from overland_planner.adapters.logging.structlog_event_log import StructlogEventLog
from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.migrator import AlembicMigrator, DatabaseStartup
from overland_planner.adapters.persistence.project_repository import SqlAlchemyCatalogUnitOfWork
from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from overland_planner.application.catalog.facade import ProjectService
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.host import MountTable
from overland_planner.application.ports.tour_solver import TourSolver
from overland_planner.bootstrap.registry import ProbeRegistry
from overland_planner.bootstrap.settings import InvalidSettingsError, Settings
from overland_planner.bootstrap.startup import StartupGate


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
    source = os.environ if environ is None else environ
    ports = external or ExternalPorts()
    clock = ports.clock or SystemClock()
    # The refusal of invalid settings is logged too, so the version cannot wait for validated settings.
    event_log: EventLog = StructlogEventLog(clock, app_version=source.get("PLANNER_GIT_SHA") or "dev")
    gate = StartupGate(event_log)
    try:
        settings = Settings.from_environ(source)
    except InvalidSettingsError as invalid:
        gate.refuse("settings", str(invalid))
    database = SqliteDatabase(settings.data_dir)
    migrator = AlembicMigrator(database, settings.migrations_dir)
    registry = ProbeRegistry()
    registry.register("clock", clock)
    registry.register("event_log", event_log)
    registry.register("database", DatabaseStartup(database, migrator))
    registry.register("tour_solver", ports.tour_solver or OrToolsTourSolver())
    health = gate.probe_in_order(registry.components())
    for name, result in health.detail().components.items():
        if result.outcome.startswith("degraded"):
            event_log.info("health.startup.degraded", component=name, reason=result.reason)

    logging.getLogger("uvicorn.access").disabled = True
    app = FastAPI(title="Overland Route Planner", version=settings.planner_git_sha)
    install_error_handlers(app)  # the {code, message} envelope for every non-2xx answer under /api (brief §5)
    app.include_router(platform_routes(health))
    app.include_router(catalog_routes(ProjectService(lambda: SqlAlchemyCatalogUnitOfWork(database), clock)))
    mount_web_page(app, settings.web_dist_dir)
    event_log.info(
        "app.started",
        routing_provider=settings.routing_provider,
        solver_budget=settings.solver_budget,
        python_version=platform.python_version(),
        alembic_revision=migrator.head(),
    )
    return app

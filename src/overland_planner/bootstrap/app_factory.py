"""Composition root (ADR-011 + Amendment 1): validate config -> wire -> migrate -> probe -> serve.

Production: `uvicorn --factory overland_planner.bootstrap.app_factory:create_app` (reads `os.environ`).
Acceptance tests: `create_app(environ, external=ExternalPorts(...))` with the same `.env` keys (brief §12)
and fakes only for external / non-deterministic ports (docs/architecture/atdd-infrastructure-policy.md).
Order: settings -> wire -> probe every registered component in wiring order (the database probe migrates it to head
first; then the file store round trip, the mount table, the `DATA_DIR` persistence verdict (D121) and the GPX
parser's embedded-sample and billion-laughs check) -> mount routes
(API and health first, then the built web page, D162) -> log `app.started`. uvicorn serves only
once the factory returns, so no request is answered before every component has reported its probe outcome. Invalid
settings or the first fatal component refuse the start (`bootstrap/startup.py`: one `health.startup.refused` line,
exit non-zero, no `app.started`); each degraded component gets one `health.startup.degraded` line {component, reason}
before `app.started`. The OR-Tools probe runs in a short-lived child process.
The shared household password (brief §12, D98), when both PLANNER_BASIC_AUTH_* keys are set, guards every path but
`/healthz`; when off, every start logs one `security.auth.disabled` warning. The event log redacts the password.

stdout carries only the JSON event lines (brief §12): uvicorn's plain-text access log is switched off here, so the
production command needs no logging flags.
"""

from __future__ import annotations

import logging
import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from fastapi import FastAPI

from overland_planner.adapters.clock.system_clock import SystemClock
from overland_planner.adapters.files.local_file_store import LocalFileStore
from overland_planner.adapters.files.proc_mount_table import ProcMountTable
from overland_planner.adapters.gpx.gpxpy_parser import GpxpyParser
from overland_planner.adapters.http.basic_auth import BasicAuthCredentials, BasicAuthMiddleware
from overland_planner.adapters.http.catalog_routes import catalog_routes
from overland_planner.adapters.http.errors import install_error_handlers
from overland_planner.adapters.http.platform_routes import platform_routes
from overland_planner.adapters.http.web_page import mount_web_page
from overland_planner.adapters.logging.structlog_event_log import StructlogEventLog
from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.migrator import AlembicMigrator, DatabaseStartup
from overland_planner.adapters.persistence.project_repository import SqlAlchemyCatalogUnitOfWork
from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from overland_planner.application.catalog.facade import ProjectService, TrackImportService
from overland_planner.application.platform.facade import DataDirPersistence, log_reason
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
    event_log: EventLog = StructlogEventLog(
        clock,
        app_version=source.get("PLANNER_GIT_SHA") or "dev",
        secret=source.get("PLANNER_BASIC_AUTH_PASSWORD"),
    )
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
    registry.register("database", DatabaseStartup(database, migrator, clock))
    file_store = LocalFileStore(settings.data_dir)
    registry.register("file_store", file_store)
    mount_table = ports.mount_table or ProcMountTable()
    registry.register("mount_table", mount_table)
    # Symlinks resolved here, so a link onto tmpfs is classified by where the data really lands (D121).
    registry.register("data_dir", DataDirPersistence(PurePosixPath(settings.data_dir.resolve()), mount_table))
    gpx_parser = GpxpyParser()
    registry.register("gpx_parser", gpx_parser)
    registry.register("tour_solver", ports.tour_solver or OrToolsTourSolver())
    health = gate.probe_in_order(registry.components())
    for name, result in health.detail().components.items():
        if result.outcome.startswith("degraded"):
            event_log.info("health.startup.degraded", component=name, reason=log_reason(result.reason))

    logging.getLogger("uvicorn.access").disabled = True
    app = FastAPI(title="Overland Route Planner", version=settings.planner_git_sha)
    install_error_handlers(app)  # the {code, message} envelope for every non-2xx answer under /api (brief §5)
    app.include_router(platform_routes(health))

    def catalog_unit_of_work() -> SqlAlchemyCatalogUnitOfWork:
        return SqlAlchemyCatalogUnitOfWork(database)

    app.include_router(
        catalog_routes(
            ProjectService(catalog_unit_of_work, clock),
            TrackImportService(catalog_unit_of_work, gpx_parser, file_store, event_log),
        )
    )
    mount_web_page(app, settings.web_dist_dir)
    auth_enabled = settings.basic_auth_user is not None and settings.basic_auth_password is not None
    if auth_enabled and settings.basic_auth_user and settings.basic_auth_password:
        credentials = BasicAuthCredentials(settings.basic_auth_user, settings.basic_auth_password.get_secret_value())
        app.add_middleware(BasicAuthMiddleware, credentials=credentials)
    else:
        event_log.warning("security.auth.disabled", reason="PLANNER_BASIC_AUTH_USER and _PASSWORD are not set")
    event_log.info(
        "app.started",
        routing_provider=settings.routing_provider,
        solver_budget=settings.solver_budget,
        python_version=platform.python_version(),
        alembic_revision=migrator.head(),
        auth_enabled=auth_enabled,
    )
    return app

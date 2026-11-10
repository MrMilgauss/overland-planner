"""Composition root (ADR-011 + Amendment 1): validate config -> wire -> migrate -> probe -> serve.

Production: `uvicorn --factory overland_planner.bootstrap.app_factory:create_app` (reads `os.environ`).
Acceptance tests: `create_app(environ, external=ExternalPorts(...))` with the same `.env` keys (brief §12)
and fakes only for external / non-deterministic ports (docs/architecture/atdd-infrastructure-policy.md).
Order: settings -> the `MOCK_PLAN` road map, read once (a bad file refuses the start for `routing_provider`) -> wire
-> probe every registered component in wiring order (the database probe migrates it to head
first; then the `plan_job_log` write-and-read round trip, the diagnostics read, the file store round trip, the mount
table, the `DATA_DIR` persistence verdict (D121), the GPX parser's embedded-sample and billion-laughs check, the GPX
writer's write and re-parse and the road map's known pair) -> mount routes
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

from fastapi import APIRouter, FastAPI

from overland_planner.adapters.clock.system_clock import SystemClock
from overland_planner.adapters.files.local_file_store import LocalFileStore
from overland_planner.adapters.files.proc_mount_table import ProcMountTable
from overland_planner.adapters.gpx.gpxpy_parser import GpxpyParser
from overland_planner.adapters.gpx.gpxpy_writer import GpxpyWriter
from overland_planner.adapters.http.basic_auth import BasicAuthCredentials, BasicAuthMiddleware
from overland_planner.adapters.http.catalog_routes import CatalogUseCases, catalog_routes
from overland_planner.adapters.http.diagnostics_routes import diagnostics_routes
from overland_planner.adapters.http.errors import install_error_handlers
from overland_planner.adapters.http.export_routes import export_routes
from overland_planner.adapters.http.planning_routes import PlanningUseCases, planning_routes
from overland_planner.adapters.http.platform_routes import platform_routes
from overland_planner.adapters.http.upload_limits import UploadLimits
from overland_planner.adapters.http.web_page import mount_web_page
from overland_planner.adapters.logging.structlog_event_log import StructlogEventLog
from overland_planner.adapters.persistence.catalog_unit_of_work import SqlAlchemyCatalogUnitOfWork
from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.diagnostics_reader import SqlAlchemyDiagnosticsReader
from overland_planner.adapters.persistence.migrator import AlembicMigrator, DatabaseStartup
from overland_planner.adapters.persistence.plan_job_log_repository import SqlAlchemyPlanJobLog
from overland_planner.adapters.persistence.planning_unit_of_work import SqlAlchemyPlanningUnitOfWork
from overland_planner.adapters.routing.mock_routing_provider import (
    InvalidRoadMapError,
    MockRoutingProvider,
    RoadMapScript,
    read_road_map,
)
from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from overland_planner.application.catalog.facade import AnchorService, PoiService, ProjectService, TrackImportService
from overland_planner.application.export.facade import GpxExportService
from overland_planner.application.planning.facade import (
    FingerprintMemo,
    PlanJobRegistry,
    PlanRequestJob,
    PlanRequestService,
    PlanRunQueries,
)
from overland_planner.application.platform.facade import (
    DataDirPersistence,
    DiagnosticsService,
    HealthService,
    log_reason,
)
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.host import MountTable
from overland_planner.application.ports.tour_solver import SolveLimits, TourSolver
from overland_planner.application.routing.facade import LegResolver
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


class _Wiring:
    """The driven adapters of one planner process, built once from the validated settings."""

    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        event_log: EventLog,
        ports: ExternalPorts,
        road_map: RoadMapScript | None,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._event_log = event_log
        self._database = SqliteDatabase(settings.data_dir)
        self.migrator = AlembicMigrator(self._database, settings.migrations_dir)
        self._plan_job_log = SqlAlchemyPlanJobLog(self._database, app_version=settings.planner_git_sha)
        self._diagnostics_reader = SqlAlchemyDiagnosticsReader(self._database)  # read-only, never the writer lock
        self._started_at = clock.now()
        self._file_store = LocalFileStore(settings.data_dir)
        self._mount_table = ports.mount_table or ProcMountTable()
        self._gpx_parser = GpxpyParser()
        self._gpx_writer = GpxpyWriter()
        # the only ROUTING_PROVIDER value until slice 06a
        self._routing_provider = MockRoutingProvider(script=road_map)
        self._tour_solver = ports.tour_solver or OrToolsTourSolver()
        self._upload_limits = UploadLimits(
            file_mb=settings.max_upload_file_mb,
            request_mb=settings.max_upload_request_mb,
            files=settings.max_upload_files,
        )

    def probe_registry(self) -> ProbeRegistry:
        """Every component in wiring order: the database probe migrates it before anything else touches it."""
        registry = ProbeRegistry()
        registry.register("clock", self._clock)
        registry.register("event_log", self._event_log)
        registry.register("database", DatabaseStartup(self._database, self.migrator, self._clock))
        registry.register("plan_job_log", self._plan_job_log)  # a write-and-read round trip; fatal like the database
        registry.register("diagnostics_reader", self._diagnostics_reader)  # one read on an empty window
        registry.register("file_store", self._file_store)
        registry.register("mount_table", self._mount_table)
        # Symlinks resolved here, so a link onto tmpfs is classified by where the data really lands (D121).
        data_dir = PurePosixPath(self._settings.data_dir.resolve())
        registry.register("data_dir", DataDirPersistence(data_dir, self._mount_table))
        registry.register("gpx_parser", self._gpx_parser)
        registry.register("gpx_writer", self._gpx_writer)
        registry.register("routing_provider", self._routing_provider)
        registry.register("tour_solver", self._tour_solver)
        return registry

    def _catalog_unit_of_work(self) -> SqlAlchemyCatalogUnitOfWork:
        return SqlAlchemyCatalogUnitOfWork(self._database, self._event_log)

    def catalog_router(self) -> APIRouter:
        use_cases = CatalogUseCases(
            projects=ProjectService(self._catalog_unit_of_work, self._clock),
            imports=TrackImportService(
                self._catalog_unit_of_work,
                self._gpx_parser,
                self._file_store,
                self._event_log,
                file_limit_mb=self._upload_limits.file_mb,
            ),
            places=PoiService(self._catalog_unit_of_work),
            anchors=AnchorService(self._catalog_unit_of_work),
        )
        return catalog_routes(use_cases, self._upload_limits)

    def _planning_unit_of_work(self) -> SqlAlchemyPlanningUnitOfWork:
        return SqlAlchemyPlanningUnitOfWork(self._database, self._event_log)

    def planning_router(self, health: HealthService) -> APIRouter:
        job = PlanRequestJob(
            unit_of_work=self._planning_unit_of_work,
            legs=LegResolver(self._routing_provider),
            solver=self._tour_solver,
            budget=self._settings.solver_budget,
            clock=self._clock,
            event_log=self._event_log,
            files=self._file_store,
            memo=FingerprintMemo(self._tour_solver.identity),
            limits=SolveLimits(self._settings.feasibility_limit_s, self._settings.optimisation_limit_s),
        )
        jobs = PlanJobRegistry(self._clock, job, self._event_log, job_log=self._plan_job_log)
        return planning_routes(
            PlanningUseCases(
                requests=PlanRequestService(self._planning_unit_of_work, health, self._event_log, jobs),
                jobs=jobs,
                runs=PlanRunQueries(self._planning_unit_of_work),
            )
        )

    def diagnostics_router(self) -> APIRouter:
        service = DiagnosticsService(
            self._diagnostics_reader,
            self._clock,
            version=self._settings.planner_git_sha,
            process_started_at=self._started_at,
        )
        return diagnostics_routes(service)

    def export_router(self) -> APIRouter:
        runs = PlanRunQueries(self._planning_unit_of_work)
        projects = ProjectService(self._catalog_unit_of_work, self._clock)
        return export_routes(GpxExportService(runs, projects, self._file_store, self._gpx_writer, self._event_log))


def create_app(
    environ: Mapping[str, str] | None = None,
    *,
    external: ExternalPorts | None = None,
) -> FastAPI:
    """Build the planner application. `environ=None` means `os.environ`; a mapping is the only source read."""
    source = os.environ if environ is None else environ
    ports = external or ExternalPorts()
    clock = ports.clock or SystemClock()
    event_log = _event_log(source, clock)
    gate = StartupGate(event_log)
    try:
        settings = Settings.from_environ(source)
    except InvalidSettingsError as invalid:
        gate.refuse("settings", str(invalid))
    wiring = _Wiring(settings, clock, event_log, ports, _road_map(settings, gate))
    health = gate.probe_in_order(wiring.probe_registry().components())
    _log_degraded(health, event_log)

    logging.getLogger("uvicorn.access").disabled = True
    app = FastAPI(title="Overland Route Planner", version=settings.planner_git_sha)
    # The {code, message} envelope for every non-2xx answer under /api (brief §5, D197).
    install_error_handlers(app, event_log)
    app.include_router(platform_routes(health))

    app.include_router(wiring.catalog_router())
    app.include_router(wiring.planning_router(health))
    app.include_router(wiring.export_router())
    app.include_router(wiring.diagnostics_router())
    mount_web_page(app, settings.web_dist_dir)
    auth_enabled = _guard_with_password(app, settings, event_log)
    event_log.info(
        "app.started",
        routing_provider=settings.routing_provider,
        solver_budget=settings.solver_budget,
        python_version=platform.python_version(),
        alembic_revision=wiring.migrator.head(),
        auth_enabled=auth_enabled,
    )
    return app


def _road_map(settings: Settings, gate: StartupGate) -> RoadMapScript | None:
    """The `MOCK_PLAN` script, read and validated once; a file that cannot be used refuses the start."""
    if settings.mock_plan is None:
        return None
    try:
        return read_road_map(settings.mock_plan)
    except InvalidRoadMapError as invalid:
        gate.refuse("routing_provider", str(invalid))


def _event_log(source: Mapping[str, str], clock: Clock) -> EventLog:
    # The refusal of invalid settings is logged too, so the version cannot wait for validated settings.
    return StructlogEventLog(
        clock,
        app_version=source.get("PLANNER_GIT_SHA") or "dev",
        secret=source.get("PLANNER_BASIC_AUTH_PASSWORD"),
    )


def _log_degraded(health: HealthService, event_log: EventLog) -> None:
    """One `health.startup.degraded` line per degraded component, before `app.started`."""
    for name, result in health.detail().components.items():
        if result.outcome.startswith("degraded"):
            event_log.info("health.startup.degraded", component=name, reason=log_reason(result.reason))


def _guard_with_password(app: FastAPI, settings: Settings, event_log: EventLog) -> bool:
    """Put the shared household password in front of the app when both keys are set; True iff it is on."""
    user, password = settings.basic_auth_user, settings.basic_auth_password
    if user is None or password is None:
        event_log.warning("security.auth.disabled", reason="PLANNER_BASIC_AUTH_USER and _PASSWORD are not set")
        return False
    app.add_middleware(BasicAuthMiddleware, credentials=BasicAuthCredentials(user, password.get_secret_value()))
    return True

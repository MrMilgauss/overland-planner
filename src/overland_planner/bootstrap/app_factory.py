"""Composition root (ADR-011 + Amendment 1): validate config -> wire -> migrate -> probe -> serve.

Production: `uvicorn --factory overland_planner.bootstrap.app_factory:create_app` (reads `os.environ`).
Acceptance tests: `create_app(environ, external=ExternalPorts(...))` with the same `.env` keys (brief §12)
and fakes only for external / non-deterministic ports (docs/architecture/atdd-infrastructure-policy.md).
Database (02-01) and probes (01-04/01-05) join this sequence in their slices.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from overland_planner.adapters.clock.system_clock import SystemClock
from overland_planner.adapters.logging.structlog_event_log import StructlogEventLog
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.host import MountTable
from overland_planner.bootstrap.settings import Settings


@dataclass(frozen=True)
class ExternalPorts:
    """Substitutes for external / non-deterministic driven ports. `None` = the production adapter.

    `tour_solver` exists only for the recorded waivers W1/W2 (atdd-infrastructure-policy.md).
    """

    clock: Clock | None = None
    mount_table: MountTable | None = None
    tour_solver: Any | None = None


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
    app = FastAPI(title="Overland Route Planner", version=settings.planner_git_sha)
    event_log.info(
        "app.started",
        routing_provider=settings.routing_provider,
        solver_budget=settings.solver_budget,
        python_version=platform.python_version(),
    )
    return app

"""Composition root (ADR-011 + Amendment 1): validate config -> wire -> migrate -> probe -> serve.

Production: `uvicorn --factory overland_planner.bootstrap.app_factory:create_app` (reads `os.environ`).
Acceptance tests: `create_app(environ, external=ExternalPorts(...))` with the same `.env` keys (brief §12)
and fakes only for external / non-deterministic ports (docs/architecture/atdd-infrastructure-policy.md).

RED scaffold (created by DISTILL, slice 01a).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from overland_planner.application.ports.clock import Clock
    from overland_planner.application.ports.host import MountTable

__SCAFFOLD__ = True


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
    """Build the planner application. `environ=None` means `os.environ`."""
    raise AssertionError("Not yet implemented -- RED scaffold: create_app (composition root, slice 01a)")

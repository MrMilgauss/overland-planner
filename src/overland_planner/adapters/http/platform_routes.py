"""Platform HTTP routes (brief §5): `GET /healthz` (own body, not the error envelope) and `GET /api/health`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from overland_planner.application.platform.facade import HealthService


def platform_routes(health: HealthService) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> JSONResponse:
        liveness = health.liveness()
        if liveness.status == "ok":
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "unhealthy", "reason": liveness.reason}, status_code=503)

    @router.get("/api/health")
    def api_health() -> dict[str, Any]:
        detail = health.detail()
        return {
            "status": detail.status,
            "components": {
                name: {"outcome": result.outcome, "reason": result.reason} for name, result in detail.components.items()
            },
            "banners": list(detail.banners),
        }

    return router

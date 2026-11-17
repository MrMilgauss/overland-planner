"""Platform HTTP routes (brief §5): `GET /healthz` (own body, not the error envelope), `GET /api/health` and
`GET /api/config/map` (the map tiles, ADR-004)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from overland_planner.adapters.http.schemas import MapConfig
from overland_planner.application.platform.facade import HealthService


def platform_routes(health: HealthService, map_config: MapConfig) -> APIRouter:
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

    @router.get("/api/config/map")
    def api_config_map() -> MapConfig:
        return map_config

    return router

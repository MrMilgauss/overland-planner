"""Platform module facade (brief §3, §11 contract 6): the only `application.platform` import other modules may use."""

from overland_planner.application.platform.health_service import HealthDetail, HealthService, HealthStatus, Liveness

__all__ = ["HealthDetail", "HealthService", "HealthStatus", "Liveness"]

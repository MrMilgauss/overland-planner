"""Platform module facade (brief §3, §11 contract 6): the only `application.platform` import other modules may use."""

from overland_planner.application.platform.data_dir_persistence import DataDirPersistence, log_reason
from overland_planner.application.platform.health_service import HealthDetail, HealthService, HealthStatus, Liveness
from overland_planner.application.platform.migration_policy import MigrationAction, PreMigrationCopies, RevisionChain

__all__ = [
    "DataDirPersistence",
    "HealthDetail",
    "HealthService",
    "HealthStatus",
    "Liveness",
    "MigrationAction",
    "PreMigrationCopies",
    "RevisionChain",
    "log_reason",
]

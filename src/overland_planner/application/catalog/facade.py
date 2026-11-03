"""Catalog module facade (brief §3, §11 contract 6): the only `application.catalog` import other modules may use."""

from overland_planner.application.catalog.project_service import ProjectNotFoundError, ProjectService

__all__ = ["ProjectNotFoundError", "ProjectService"]

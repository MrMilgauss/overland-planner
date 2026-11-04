"""Catalog module facade (brief §3, §11 contract 6): the only `application.catalog` import other modules may use."""

from overland_planner.application.catalog.anchor_service import AnchorService, ItemNotFoundError
from overland_planner.application.catalog.poi_service import PoiService
from overland_planner.application.catalog.project_service import ProjectNotFoundError, ProjectService
from overland_planner.application.catalog.track_import_service import (
    MIB,
    InvalidCanonicalPointsFileError,
    TrackFile,
    TrackFilesRefusedError,
    TrackImportService,
    canonical_points_file,
    parse_canonical_points_file,
)

__all__ = [
    "MIB",
    "AnchorService",
    "InvalidCanonicalPointsFileError",
    "ItemNotFoundError",
    "PoiService",
    "ProjectNotFoundError",
    "ProjectService",
    "TrackFile",
    "TrackFilesRefusedError",
    "TrackImportService",
    "canonical_points_file",
    "parse_canonical_points_file",
]

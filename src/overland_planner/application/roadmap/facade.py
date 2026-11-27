"""Road-map module facade (brief §11 contract 6): the only `application.roadmap` import other modules may use."""

from overland_planner.application.ports.region_catalogue import CatalogueUnavailableError
from overland_planner.application.ports.road_map_changes import ChangesUnavailableError
from overland_planner.application.roadmap.coverage_service import CoverageService, TripCoverage, TripGroup
from overland_planner.application.roadmap.service import (
    SEED_REGION_KEYS,
    CatalogueHit,
    ChangeSummary,
    PlannedChange,
    RegionRef,
    RoadMapService,
    SearchTooShortError,
    ServedMapView,
    ServedRegionView,
)
from overland_planner.domain.roadmap.region_choice import Refusal

__all__ = [
    "SEED_REGION_KEYS",
    "CatalogueHit",
    "CatalogueUnavailableError",
    "ChangeSummary",
    "ChangesUnavailableError",
    "CoverageService",
    "PlannedChange",
    "Refusal",
    "RegionRef",
    "RoadMapService",
    "SearchTooShortError",
    "ServedMapView",
    "ServedRegionView",
    "TripCoverage",
    "TripGroup",
]

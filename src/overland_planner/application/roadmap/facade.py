"""Road-map module facade (brief §11 contract 6): the only `application.roadmap` import other modules may use."""

from overland_planner.application.ports.region_catalogue import CatalogueUnavailableError
from overland_planner.application.roadmap.coverage_service import CoverageService, TripCoverage, TripGroup
from overland_planner.application.roadmap.service import (
    CatalogueHit,
    ChangeSummary,
    RegionRef,
    RoadMapService,
    SearchTooShortError,
    ServedMapView,
    ServedRegionView,
)
from overland_planner.domain.roadmap.region_choice import Refusal

__all__ = [
    "CatalogueHit",
    "CatalogueUnavailableError",
    "ChangeSummary",
    "CoverageService",
    "Refusal",
    "RegionRef",
    "RoadMapService",
    "SearchTooShortError",
    "ServedMapView",
    "ServedRegionView",
    "TripCoverage",
    "TripGroup",
]

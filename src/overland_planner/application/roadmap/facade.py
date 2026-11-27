"""Road-map module facade (brief §11 contract 6): the only `application.roadmap` import other modules may use."""

from overland_planner.application.ports.region_catalogue import CatalogueUnavailableError
from overland_planner.application.roadmap.coverage_service import CoverageService, TripCoverage, TripGroup
from overland_planner.application.roadmap.service import (
    CatalogueHit,
    RoadMapService,
    SearchTooShortError,
    ServedMapView,
    ServedRegionView,
)

__all__ = [
    "CatalogueHit",
    "CatalogueUnavailableError",
    "CoverageService",
    "RoadMapService",
    "SearchTooShortError",
    "ServedMapView",
    "ServedRegionView",
    "TripCoverage",
    "TripGroup",
]

"""Road-map module facade (brief §11 contract 6): the only `application.roadmap` import other modules may use."""

from overland_planner.application.ports.place_search import PlaceHit, PlaceSearch, PlaceSearchUnavailableError
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

MIN_PLACE_LETTERS = 2


class PlaceNameTooShortError(ValueError):
    """A place search with fewer than two letters: nothing is sent to anybody."""

    def __init__(self) -> None:
        super().__init__("A place name needs at least two letters")


class PlaceSearchService:
    """Place search by name (D307): the typed words are tidied and only then sent, and only when long enough."""

    def __init__(self, places: PlaceSearch) -> None:
        self._places = places

    def search(self, words: str) -> tuple[PlaceHit, ...]:
        wanted = " ".join(words.split())
        if len(wanted) < MIN_PLACE_LETTERS:
            raise PlaceNameTooShortError
        return self._places.search(wanted)


__all__ = [
    "SEED_REGION_KEYS",
    "CatalogueHit",
    "CatalogueUnavailableError",
    "ChangeSummary",
    "ChangesUnavailableError",
    "CoverageService",
    "PlaceHit",
    "PlaceNameTooShortError",
    "PlaceSearchService",
    "PlaceSearchUnavailableError",
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

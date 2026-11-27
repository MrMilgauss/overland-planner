"""Which regions and which date the served map has (D301, D314, D315).

The engine says which map it serves (`ServedMap`, uncached); the tileset volume lists what each directory holds
(`TilesetStore`); the domain's `select_served` matches the two. No match is an unknown map that still carries its date
when the engine gave one. While the engine does not answer (the build stops it) the last matched map is kept in
memory, and a restarted planner falls back to the tileset the rebuild's progress note says is served.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from overland_planner.application.ports.region_catalogue import CatalogueUnavailableError, RegionCatalogue
from overland_planner.application.ports.served_map import ServedMap
from overland_planner.application.ports.tileset_store import TilesetListing, TilesetStore
from overland_planner.domain.roadmap.coverage import RoadMapCoverage
from overland_planner.domain.roadmap.served_map import ServedId, select_served


@dataclass(frozen=True)
class ServedRegionView:
    key: str
    name: str
    parent_name: str | None
    bytes: int


@dataclass(frozen=True)
class ServedMapView:
    known: bool
    map_date: datetime | None
    regions: tuple[ServedRegionView, ...]
    total_bytes: int
    # The real outlines, for judging a trip; not part of what the served map says about itself.
    coverage: RoadMapCoverage = field(default=RoadMapCoverage(()), compare=False)


MIN_SEARCH_LETTERS = 2
MAX_SEARCH_RESULTS = 8


class SearchTooShortError(ValueError):
    """A region search with fewer than two letters: nothing is asked of anybody."""

    def __init__(self) -> None:
        super().__init__("A region search needs at least two letters")


@dataclass(frozen=True)
class CatalogueHit:
    key: str
    name: str
    parent_name: str | None
    bytes: int | None  # None while the region service cannot say


def _date(epoch: int | None) -> datetime | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, UTC)


class RoadMapService:
    def __init__(
        self, served_map: ServedMap | None, store: TilesetStore, catalogue: RegionCatalogue | None = None
    ) -> None:
        self._served_map = served_map
        self._store = store
        self._catalogue = catalogue
        self._last_matched: ServedMapView | None = None

    def served(self) -> ServedMapView:
        answered = None if self._served_map is None else self._served_map.served_id()
        if answered is None and self._last_matched is not None:
            return self._last_matched
        served_id = self._store.serving_hint() if answered is None else answered
        view = self._view(self._store.listing(), served_id)
        if view.known:
            self._last_matched = view
        return view

    def search_catalogue(self, words: str) -> tuple[CatalogueHit, ...]:
        """Regions of the free list whose name holds the words, name starting with them first; at most eight, each
        with its parent's name and size (None while the region service cannot say)."""
        wanted = " ".join(words.split()).casefold()
        if len(wanted) < MIN_SEARCH_LETTERS:
            raise SearchTooShortError
        if self._catalogue is None:
            raise CatalogueUnavailableError("no list of regions is set up")
        entries = self._catalogue.entries()
        names = {entry.key: entry.name for entry in entries}
        matching = sorted(
            (entry for entry in entries if wanted in entry.name.casefold()),
            key=lambda entry: (not entry.name.casefold().startswith(wanted), entry.name.casefold(), entry.key),
        )
        return tuple(
            CatalogueHit(entry.key, entry.name, names.get(entry.parent or ""), self._catalogue.size_of(entry))
            for entry in matching[:MAX_SEARCH_RESULTS]
        )

    @staticmethod
    def _view(listing: TilesetListing, served_id: ServedId | None) -> ServedMapView:
        entry = select_served(listing.entries, served_id)
        if entry is None:
            date = served_id if isinstance(served_id, int) else listing.built_at.get(str(served_id))
            return ServedMapView(known=False, map_date=_date(date), regions=(), total_bytes=0)
        regions = tuple(
            ServedRegionView(region.key, region.name, region.parent_name, region.bytes)
            for region in listing.regions[entry.name]
        )
        return ServedMapView(
            known=True,
            map_date=_date(listing.built_at[entry.name]),
            regions=regions,
            total_bytes=sum(region.bytes for region in regions),
            coverage=RoadMapCoverage(tuple((region.name, region.outline) for region in listing.regions[entry.name])),
        )

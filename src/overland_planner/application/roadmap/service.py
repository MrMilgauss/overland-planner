"""Which regions and which date the served map has (D301, D314, D315).

The engine says which map it serves (`ServedMap`, uncached); the tileset volume lists what each directory holds
(`TilesetStore`); the domain's `select_served` matches the two. No match is an unknown map that still carries its date
when the engine gave one. While the engine does not answer (the build stops it) the last matched map is kept in
memory, and a restarted planner falls back to the tileset the rebuild's progress note says is served.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from overland_planner.application.ports.served_map import ServedMap
from overland_planner.application.ports.tileset_store import TilesetListing, TilesetStore
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


def _date(epoch: int | None) -> datetime | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, UTC)


class RoadMapService:
    def __init__(self, served_map: ServedMap | None, store: TilesetStore) -> None:
        self._served_map = served_map
        self._store = store
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
        )

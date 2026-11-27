"""Which regions and which date the served map has (D301, D314, D315).

The engine says which map it serves (`ServedMap`, uncached); the tileset volume lists what each directory holds
(`TilesetStore`); the domain's `select_served` matches the two. No match is an unknown map that still carries its date
when the engine gave one. While the engine does not answer (the build stops it) the last matched map is kept in
memory, and a restarted planner falls back to the tileset the rebuild's progress note says is served.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from overland_planner.application.ports.region_catalogue import (
    CatalogueEntry,
    CatalogueUnavailableError,
    RegionCatalogue,
)
from overland_planner.application.ports.served_map import ServedMap
from overland_planner.application.ports.tileset_store import TilesetListing, TilesetStore
from overland_planner.domain.roadmap.coverage import RoadMapCoverage
from overland_planner.domain.roadmap.outline import Outline
from overland_planner.domain.roadmap.region_choice import CatalogRegion, RegionChoice
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
    outlines: Mapping[str, Outline] = field(default_factory=dict, compare=False)


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
    in_map: bool  # served already, or part of a served region


@dataclass(frozen=True)
class RegionRef:
    key: str
    name: str


@dataclass(frozen=True)
class ChangeSummary:
    """What a chosen set of regions would cost and change, before anything is written (D305, D308)."""

    added: tuple[RegionRef, ...]
    removed: tuple[RegionRef, ...]
    total_bytes: int
    total_minutes: int
    pause_minutes: int
    land_groups: tuple[tuple[str, ...], ...]  # region names, one tuple per group linked by land
    not_linked_note: str | None


def _date(epoch: int | None) -> datetime | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, UTC)


def _ancestors(key: str, parent_of: Mapping[str, str | None]) -> list[str]:
    found: list[str] = []
    parent = parent_of.get(key)
    while parent is not None and parent in parent_of and parent not in found:
        found.append(parent)
        parent = parent_of[parent]
    return found


def _not_linked_note(
    choice: RegionChoice, outlines: Mapping[str, Outline], regions: Mapping[str, CatalogRegion]
) -> str | None:
    """Words for the owner when the chosen regions are in several groups linked by land: the smallest group is named,
    each group by its one region or by the nearest parent its regions share (information, never a refusal, D300)."""
    groups = choice.land_groups(outlines)
    if len(groups) < 2:
        return None
    apart = min(groups, key=len)
    others = [group for group in groups if group is not apart]
    apart_label = _group_label(apart, regions)
    inside = ", or inside ".join(_group_label(group, regions) for group in others)
    return (
        f"{apart_label} is not linked by land to your other regions. "
        f"Trips inside {apart_label}, or inside {inside}, are fine; a trip between them can't be planned."
    )


def _group_label(group: tuple[str, ...], regions: Mapping[str, CatalogRegion]) -> str:
    if len(group) == 1:
        return regions[group[0]].name
    parent_of = {key: region.parent for key, region in regions.items()}
    shared = next(
        (a for a in _ancestors(group[0], parent_of) if all(a in _ancestors(key, parent_of) for key in group[1:])), None
    )
    return regions[shared].name if shared else " and ".join(regions[key].name for key in group)


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
        by_key = {entry.key: entry for entry in entries}
        parent_of = {entry.key: entry.parent for entry in entries}
        served = {region.key for region in self.served().regions}
        matching = sorted(
            (entry for entry in entries if wanted in entry.name.casefold()),
            key=lambda entry: (not entry.name.casefold().startswith(wanted), entry.name.casefold(), entry.key),
        )
        return tuple(
            CatalogueHit(
                entry.key,
                entry.name,
                by_key[entry.parent].name if entry.parent in by_key else None,
                self._catalogue.size_of(entry),
                bool(served & {entry.key, *_ancestors(entry.key, parent_of)}),
            )
            for entry in matching[:MAX_SEARCH_RESULTS]
        )

    def preview_change(self, region_keys: Sequence[str]) -> ChangeSummary:
        """The summary of making the map hold exactly these regions; writes nothing. Only the border of a region not
        served is fetched, and only the size of a region not served is asked. Raises `Refusal` for a region unknown
        or overlapping another, `CatalogueUnavailableError` when the list, a size or a border cannot be had."""
        if self._catalogue is None:
            raise CatalogueUnavailableError("no list of regions is set up")
        by_key = {entry.key: entry for entry in self._catalogue.entries()}
        served = self.served()
        held = {region.key: region for region in served.regions}
        wanted = set(region_keys)
        regions = {
            key: CatalogRegion(
                key,
                held[key].name if key in held else entry.name,
                entry.parent,
                held[key].bytes if key in held else self._size(self._catalogue, entry) if key in wanted else 0,
            )
            for key, entry in by_key.items()
        } | {key: CatalogRegion(key, r.name, None, r.bytes) for key, r in held.items() if key not in by_key}
        choice = RegionChoice(regions, frozenset(held), frozenset())
        for key in sorted(wanted):
            choice = choice.add(key)
        outlines = {
            key: served.outlines[key] if key in served.outlines else self._catalogue.outline_of(by_key[key])
            for key in choice.chosen
        }
        names = {key: region.name for key, region in regions.items()}
        groups = tuple(
            sorted(
                (tuple(sorted(names[key] for key in group)) for group in choice.land_groups(outlines)),
            )
        )
        figures = choice.estimate()
        return ChangeSummary(
            added=tuple(RegionRef(key, names[key]) for key in sorted(choice.added)),
            removed=tuple(RegionRef(key, names[key]) for key in sorted(choice.removed)),
            total_bytes=choice.total_bytes,
            total_minutes=figures.total_minutes,
            pause_minutes=figures.pause_minutes,
            land_groups=groups,
            not_linked_note=_not_linked_note(choice, outlines, regions),
        )

    @staticmethod
    def _size(catalogue: RegionCatalogue, entry: CatalogueEntry) -> int:
        size = catalogue.size_of(entry)
        if size is None:
            raise CatalogueUnavailableError(f"the size of {entry.name} cannot be had")
        return size

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
            outlines={region.key: region.outline for region in listing.regions[entry.name]},
        )

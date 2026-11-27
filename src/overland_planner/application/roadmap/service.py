"""Which regions and which date the served map has (D301, D314, D315).

The engine says which map it serves (`ServedMap`, uncached); the tileset volume lists what each directory holds
(`TilesetStore`); the domain's `select_served` matches the two. No match is an unknown map that still carries its date
when the engine gave one. While the engine does not answer (the build stops it) the last matched map is kept in
memory, and a restarted planner falls back to the tileset the rebuild's progress note says is served.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.region_catalogue import (
    CatalogueEntry,
    CatalogueUnavailableError,
    RegionCatalogue,
)
from overland_planner.application.ports.road_map_changes import (
    ChangeRequest,
    ChangesUnavailableError,
    RequestedRegion,
    RoadMapChanges,
)
from overland_planner.application.ports.served_map import ServedMap
from overland_planner.application.ports.tileset_store import TilesetListing, TilesetStore
from overland_planner.domain.roadmap.coverage import RoadMapCoverage
from overland_planner.domain.roadmap.outline import Outline
from overland_planner.domain.roadmap.region_choice import CatalogRegion, Refusal, RegionChoice
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


DEFAULT_MAX_GB = 8.0
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


@dataclass(frozen=True)
class PlannedChange:
    """The change waiting for the helper, against the map served now."""

    requested_at: datetime
    start_at: datetime | None
    added: tuple[RegionRef, ...]
    removed: tuple[RegionRef, ...]


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


@dataclass(frozen=True)
class _Chosen:
    """A choice of regions with what was learned to make it: the list's entries and the map served now."""

    catalogue: RegionCatalogue
    choice: RegionChoice
    regions: Mapping[str, CatalogRegion]
    by_key: Mapping[str, CatalogueEntry]
    served: ServedMapView


_KEY = re.compile(r"[a-z0-9-]+(/[a-z0-9-]+)?")
_MAX_NAME_BYTES = 120


def _readable_text(text: str) -> bool:
    """The helper's rule for a name: printable, no tab or control character, 1 to 120 bytes."""
    return text.isprintable() and 0 < len(text.encode("utf-8")) <= _MAX_NAME_BYTES


def _plain_address(address: str) -> bool:
    return address.isprintable() and ".." not in address.split("/") and bool(address)


def _requested(chosen: _Chosen, key: str) -> RequestedRegion:
    """The region as the helper reads it, or a refusal when the list does not hold it or the helper would refuse it."""
    entry = chosen.by_key.get(key)
    parent = None if entry is None or entry.parent not in chosen.by_key else chosen.by_key[str(entry.parent)].name
    if (
        entry is None
        or _KEY.fullmatch(key) is None
        or not _readable_text(entry.name)
        or (parent is not None and not _readable_text(parent))
        or not (_plain_address(entry.pbf_url) and _plain_address(entry.poly_url))
    ):
        raise Refusal("unknown_region", f"{key} cannot be added to the road map", key=key)
    return RequestedRegion(key, entry.name, parent, entry.pbf_url, entry.poly_url, chosen.regions[key].bytes)


class RoadMapService:
    def __init__(
        self,
        served_map: ServedMap | None,
        store: TilesetStore,
        catalogue: RegionCatalogue | None = None,
        changes: RoadMapChanges | None = None,
        clock: Clock | None = None,
        max_gb: float = DEFAULT_MAX_GB,
    ) -> None:
        self._served_map = served_map
        self._store = store
        self._catalogue = catalogue
        self._changes = changes
        self._clock = clock
        self._max_gb = max_gb
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
        return self._summary(self._choose(region_keys))

    def plan_change(self, region_keys: Sequence[str], start_at: datetime | None = None) -> ChangeSummary:
        """Keep the change ready for the helper and answer with its summary; the served map is left as it is. Raises
        `ChangesUnavailableError` when changes cannot be kept, `Refusal` for a region unknown, overlapping another,
        one the helper would refuse to read, or a download above the limit (nothing is fetched for the last), and
        `CatalogueUnavailableError` as `preview_change` does. Nothing is written unless every check passed."""
        changes, clock = self._open_changes()
        chosen = self._choose(region_keys)
        chosen.choice.check_size(self._max_gb)
        request = self._request(chosen, start_at, clock.now())
        summary = self._summary(chosen)
        changes.queue(request, [ref.name for ref in summary.added], [ref.name for ref in summary.removed])
        return summary

    def cancel_change(self) -> bool:
        """Make the waiting change one the helper can no longer take; False when none is left to cancel."""
        return self._changes is not None and self._changes.cancel()

    def planned_change(self) -> PlannedChange | None:
        """The change waiting for the helper, told against the map served now."""
        request = None if self._changes is None else self._changes.pending()
        if request is None:
            return None
        served = {region.key: region.name for region in self.served().regions}
        kept = {region.key for region in request.regions}
        return PlannedChange(
            requested_at=request.requested_at,
            start_at=request.start_at,
            added=tuple(RegionRef(region.key, region.name) for region in request.regions if region.key not in served),
            removed=tuple(RegionRef(key, name) for key, name in sorted(served.items()) if key not in kept),
        )

    @property
    def max_gb(self) -> float:
        """The most a change may download, in GB."""
        return self._max_gb

    def changes_available(self) -> bool:
        return self._changes is not None and self._changes.available()

    def _open_changes(self) -> tuple[RoadMapChanges, Clock]:
        if self._changes is None or self._clock is None or not self._changes.available():
            raise ChangesUnavailableError("the place where changes are kept cannot be written")
        return self._changes, self._clock

    def _choose(self, region_keys: Sequence[str]) -> _Chosen:
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
        for key in sorted(wanted, key=lambda key: (key not in held, key)):  # what is served first: the new one overlaps
            choice = choice.add(key)
        return _Chosen(self._catalogue, choice, regions, by_key, served)

    @staticmethod
    def _summary(chosen: _Chosen) -> ChangeSummary:
        choice, regions, served = chosen.choice, chosen.regions, chosen.served
        outlines = {
            key: served.outlines[key] if key in served.outlines else chosen.catalogue.outline_of(chosen.by_key[key])
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
    def _request(chosen: _Chosen, start_at: datetime | None, now: datetime) -> ChangeRequest:
        written = tuple(_requested(chosen, key) for key in sorted(chosen.choice.chosen))
        return ChangeRequest(requested_at=now, start_at=start_at, regions=written)

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

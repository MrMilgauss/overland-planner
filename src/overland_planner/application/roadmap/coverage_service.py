"""A trip judged against the served borders (D302, D308): which included items lie outside the map, and which groups of
regions not linked by land the stops fall in.

A place is outside by its point, a trail by its entry or its exit (the planner drives to and from those points; the
middle is irrelevant). The served map is read, never a pending choice (D301). An unknown map judges nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from overland_planner.application.roadmap.service import ServedMapView
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.roadmap.coverage import RoadMapCoverage
from overland_planner.domain.roadmap.outline import Outline


@dataclass(frozen=True)
class TripGroup:
    regions: tuple[str, ...]
    item_ids: tuple[str, ...]


@dataclass(frozen=True)
class TripCoverage:
    known: bool
    map_date: datetime | None
    regions: tuple[str, ...]
    outside_item_ids: tuple[str, ...]
    groups: tuple[TripGroup, ...]


def _stops(item: CatalogItem) -> tuple[Coordinate, ...]:
    """Where the planner drives to and from: a place's point, a trail's entry and exit (never its middle)."""
    if isinstance(item, TrackItem):
        return (item.entry, item.exit)
    return (item.location,)


class CoverageService:
    def __init__(self, items: Callable[[str], Sequence[CatalogItem]], served: Callable[[], ServedMapView]) -> None:
        self._items = items
        self._served = served

    def of(self, project_id: str) -> TripCoverage:
        """Raises the catalog's not-found error for an unknown project."""
        included = [item for item in self._items(project_id) if item.included]
        served = self._served()
        if not served.known:
            return TripCoverage(known=False, map_date=served.map_date, regions=(), outside_item_ids=(), groups=())
        coverage = served.coverage
        outside = tuple(item.id for item in included if not all(coverage.contains(point) for point in _stops(item)))
        return TripCoverage(
            known=True,
            map_date=served.map_date,
            regions=tuple(sorted(name for name, _ in coverage.regions)),
            outside_item_ids=outside,
            groups=self._groups(coverage, included),
        )

    @staticmethod
    def _groups(coverage: RoadMapCoverage, items: Sequence[CatalogItem]) -> tuple[TripGroup, ...]:
        by_name = dict(coverage.regions)
        held = (
            TripGroup(regions=names, item_ids=tuple(i.id for i in items if _is_in(names, by_name, _stops(i))))
            for names in coverage.land_groups()
        )
        return tuple(group for group in held if group.item_ids)


def _is_in(names: tuple[str, ...], outlines: dict[str, Outline], points: tuple[Coordinate, ...]) -> bool:
    return any(outlines[name].contains(point) for name in names for point in points)

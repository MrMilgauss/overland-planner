"""Catalog items of a trip project (brief §3, §5 D107): imported tracks and POIs (`poi.py`). Pure domain.

A track keeps its points in recorded order (HC-1): entry is the first recorded point, exit the last. Its full
resolution points live in a version-addressed file (`canonical.v{direction_version}.json`, ADR-018); the item holds
the hashes that address the original upload and that file, plus the statistics shown in the item list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.poi import AnchorRole, PoiItem

ItemType = Literal["track", "poi"]


@dataclass(frozen=True)
class TrackItem:
    """An imported track. `anchor` is always `None`: a track is never an anchor (D6)."""

    id: str
    project_id: str
    name: str
    description: str | None
    original_sha256: str
    canonical_sha256: str
    direction_version: int
    point_count: int
    entry: Coordinate
    exit: Coordinate
    length_m: float
    included: bool = True
    anchor: AnchorRole | None = None

    @property
    def type(self) -> ItemType:
        return "track"


CatalogItem = TrackItem | PoiItem

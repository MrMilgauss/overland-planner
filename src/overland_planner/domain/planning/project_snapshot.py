"""What planning reads of a project: its read-only view of the catalog (brief section 8). Pure domain.

A track is reached at its entry and left at its exit (HC-1); a POI is reached and left at its location.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.project import DEFAULT_OFFROAD_SPEED, OffroadSpeed

Anchor = Literal["Start", "End"]


def reached_at(item: CatalogItem) -> Coordinate:
    return item.entry if isinstance(item, TrackItem) else item.location


def left_at(item: CatalogItem) -> Coordinate:
    return item.exit if isinstance(item, TrackItem) else item.location


@dataclass(frozen=True)
class ProjectSnapshot:
    start_item_id: str | None = None
    end_item_id: str | None = None
    items: tuple[CatalogItem, ...] = ()
    offroad_speed: OffroadSpeed = DEFAULT_OFFROAD_SPEED

    def missing_anchor(self) -> Anchor | None:
        """The anchor to set first: with both missing, the Start."""
        if self.start_item_id is None:
            return "Start"
        if self.end_item_id is None:
            return "End"
        return None

    def item(self, item_id: str | None) -> CatalogItem:
        """Raises `KeyError` for an item outside the snapshot, an anchor not set included."""
        items_by_id: dict[str | None, CatalogItem] = {item.id: item for item in self.items}
        return items_by_id[item_id]

    def start(self) -> CatalogItem:
        return self.item(self.start_item_id)

    def end(self) -> CatalogItem:
        return self.item(self.end_item_id)

    def visited_items(self) -> tuple[CatalogItem, ...]:
        """The Included items other than the anchors: the ones to place between Start and End (HC-2)."""
        anchors = (self.start_item_id, self.end_item_id)
        return tuple(item for item in self.items if item.included and item.id not in anchors)

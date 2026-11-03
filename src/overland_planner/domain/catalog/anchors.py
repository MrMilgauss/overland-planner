"""Trip anchors (HC-2, D6, brief §5 D183): one Start and one End, both POIs of the project; they may be the same POI.

The item list shows each item's anchor: `start_end` for the one POI of a round trip, `start` and `end` for a one-way
trip, `None` for every other item. Pure domain.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from overland_planner.domain.catalog.item import CatalogItem
from overland_planner.domain.catalog.poi import AnchorRole, PoiItem


class AnchorNotAPlaceError(ValueError):
    """A Start or End that is a track (D6) or an item of another project."""

    def __init__(self) -> None:
        super().__init__("Only a place of this project can be the Start or End")


@dataclass(frozen=True)
class Anchors:
    """The Start and End item ids of a project; `None` until they are set."""

    start_item_id: str | None = None
    end_item_id: str | None = None

    @classmethod
    def chosen(cls, project_id: str, start: CatalogItem, end: CatalogItem) -> Anchors:
        """Raises `AnchorNotAPlaceError` unless both are POIs of the project."""
        for item in (start, end):
            if not isinstance(item, PoiItem) or item.project_id != project_id:
                raise AnchorNotAPlaceError()
        return cls(start_item_id=start.id, end_item_id=end.id)

    def role_of(self, item_id: str) -> AnchorRole | None:
        is_start, is_end = item_id == self.start_item_id, item_id == self.end_item_id
        if is_start and is_end:
            return "start_end"
        if is_start:
            return "start"
        if is_end:
            return "end"
        return None

    def marked(self, items: Iterable[CatalogItem]) -> list[CatalogItem]:
        """The items with the anchor each one shows in the item list."""
        return [replace(item, anchor=self.role_of(item.id)) for item in items]

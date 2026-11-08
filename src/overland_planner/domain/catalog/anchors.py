"""Trip anchors (HC-2, D6, brief §5 D183): one Start and one End, both POIs of the project; they may be the same POI.

Either may be unset (slice 02): Calculate names the one that is missing. Removing the item an anchor held clears it.

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
        super().__init__("Only places (POIs) can be the Start or End")


@dataclass(frozen=True)
class Anchors:
    """The Start and End item ids of a project; `None` until they are set."""

    start_item_id: str | None = None
    end_item_id: str | None = None

    @classmethod
    def chosen(cls, project_id: str, start: CatalogItem | None, end: CatalogItem | None) -> Anchors:
        """`None` leaves that anchor unset. Raises `AnchorNotAPlaceError` unless each one set is a project POI."""
        for item in (start, end):
            if item is not None and (not isinstance(item, PoiItem) or item.project_id != project_id):
                raise AnchorNotAPlaceError()
        return cls(start_item_id=_id_of(start), end_item_id=_id_of(end))

    def without(self, item_id: str) -> Anchors:
        """The anchors once this item is gone: an anchor it held is unset, the other one stays."""
        return Anchors(
            start_item_id=None if self.start_item_id == item_id else self.start_item_id,
            end_item_id=None if self.end_item_id == item_id else self.end_item_id,
        )

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


def _id_of(item: CatalogItem | None) -> str | None:
    return None if item is None else item.id

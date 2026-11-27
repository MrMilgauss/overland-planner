"""Which tileset directory is the served map (D301, D314): a pure match of the engine's answer against a listing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

ServedId = int | str


@dataclass(frozen=True)
class TilesetEntry:
    """One directory of the tileset volume: its name, the mtime of its tar, and whether a valid record was read."""

    name: str
    tar_mtime: int | None
    has_record: bool


def select_served(listing: Sequence[TilesetEntry], served_id: ServedId | None) -> TilesetEntry | None:
    """The one directory the engine serves, or None (unknown): no match, a doubtful match or no valid record."""
    if served_id is None:
        return None
    if isinstance(served_id, int):
        matches = [entry for entry in listing if entry.tar_mtime == served_id]
    else:
        matches = [entry for entry in listing if entry.name == served_id]
    if len(matches) != 1 or not matches[0].has_record:
        return None
    return matches[0]

"""Driven port: the tileset directories of the road-map volume and what each one records (D301, D314).

A listing is data only: per directory its name and `valhalla_tiles.tar` mtime (`TilesetEntry`), the date of its map,
and, when its record and every outline the record names read well, the regions it holds. No matching happens here:
`select_served` picks the served directory. A missing volume, record or outline is an unknown map, never an error;
only an outline that exists and is not a border is `damaged` (it degrades the component, D310).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from overland_planner.application.ports.probe import Probeable
from overland_planner.domain.roadmap.outline import Outline
from overland_planner.domain.roadmap.served_map import TilesetEntry


@dataclass(frozen=True)
class ServedRegion:
    key: str
    name: str
    parent_name: str | None
    bytes: int
    outline: Outline


@dataclass(frozen=True)
class TilesetListing:
    entries: tuple[TilesetEntry, ...] = ()
    regions: Mapping[str, tuple[ServedRegion, ...]] = field(default_factory=dict)  # by directory, valid records only
    built_at: Mapping[str, int] = field(default_factory=dict)  # by directory: epoch of the map date
    damaged: tuple[str, ...] = ()  # directories with an outline that exists and cannot be read


class TilesetStore(Probeable, Protocol):
    def listing(self) -> TilesetListing: ...

    def serving_hint(self) -> str | None:
        """The tileset the last rebuild's progress note says is served, or None."""
        ...

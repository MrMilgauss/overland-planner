"""Driven port: the free list of regions the road map can be built from (D306, D315).

The list is data only: per region its key (the list's own id), its name, its parent's key and the addresses of its
`.osm.pbf` and `.poly` (the list's own, never built by the planner). Matching a name and naming a parent is the
service's work, never the adapter's. Only region details ever leave the house: the list itself, and one size per
region the owner is shown. The list is kept between runs; when the service does not answer the kept copy is used, and
only without any copy is it `CatalogueUnavailableError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from overland_planner.application.ports.probe import Probeable


class CatalogueUnavailableError(Exception):
    """The list is not kept and the region service did not give it."""


@dataclass(frozen=True)
class CatalogueEntry:
    key: str
    name: str
    parent: str | None
    pbf_url: str
    poly_url: str


class RegionCatalogue(Probeable, Protocol):
    def entries(self) -> tuple[CatalogueEntry, ...]:
        """Every region the list offers; raises `CatalogueUnavailableError`."""
        ...

    def size_of(self, entry: CatalogueEntry) -> int | None:
        """Bytes of the region's map data, asked once and remembered; None when the service cannot say."""
        ...

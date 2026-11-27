"""Driven port: search for a place by its name (D307, D314, ADR-019).

Only the typed words ever leave the house. The answer is at most five places, each with the name, the region it lies
in (empty when the service names none) and the country, and its point. Nothing matching is an empty tuple, never an
error; a service that is switched off, busy, down or garbled is `PlaceSearchUnavailableError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from overland_planner.application.ports.probe import Probeable

MAX_PLACES = 5


class PlaceSearchUnavailableError(Exception):
    """The search is switched off, or the service did not give a readable answer."""


@dataclass(frozen=True)
class PlaceHit:
    name: str
    region: str
    country: str
    lat: float
    lon: float
    area: str = ""  # the county or the like, empty when the service names none


class PlaceSearch(Probeable, Protocol):
    def search(self, words: str) -> tuple[PlaceHit, ...]:
        """Up to `MAX_PLACES` places for the words; raises `PlaceSearchUnavailableError`."""
        ...

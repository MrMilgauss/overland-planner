"""Driven port: the planned road-map change, kept ready for the Pi's helper (D303, D315).

One change waits at a time. The planner writes it as a request (all or nothing: the helper never sees half a request)
and may cancel it while the helper has not taken it; whoever takes or cancels first wins. The planner never
evaluates, runs or deletes anything: the helper owns every other file of the folder.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from overland_planner.application.ports.probe import Probeable


class ChangesUnavailableError(Exception):
    """The place where changes are kept cannot be written."""


@dataclass(frozen=True)
class RequestedRegion:
    key: str
    name: str
    parent_name: str | None
    pbf_url: str
    poly_url: str
    bytes: int


@dataclass(frozen=True)
class ChangeRequest:
    """The regions the new map holds, and when the rebuild may start (None: as soon as the helper looks)."""

    requested_at: datetime
    start_at: datetime | None
    regions: tuple[RequestedRegion, ...]


class RoadMapChanges(Probeable, Protocol):
    def available(self) -> bool:
        """Whether a change can be kept right now (the place exists and may be written)."""
        ...

    def queue(self, request: ChangeRequest, added: Sequence[str], removed: Sequence[str]) -> None:
        """Keep the request ready for the helper, for the report naming what is added and removed. Moves the last
        result aside and forgets a cancel. Replaces nothing half-written;
        raises `ChangesUnavailableError` and leaves nothing behind when it cannot."""
        ...

    def waiting(self) -> bool:
        """Whether a request waits for the helper (readable or not)."""
        ...

    def running(self) -> bool:
        """Whether the helper has taken a request and is rebuilding."""
        ...

    def cancel(self) -> bool:
        """Make the waiting request one the helper can no longer take; False when none is left to cancel."""
        ...

    def pending(self) -> ChangeRequest | None:
        """The request waiting for the helper, None when there is none (or it cannot be read)."""
        ...

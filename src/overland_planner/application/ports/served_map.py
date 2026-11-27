"""Driven port: which map the routing engine serves, as the engine says it (D301, D314).

The answer is typed data, never a verdict: an epoch (Valhalla's `tileset_last_modified`) or a directory name (the
offline road map), or None when the engine cannot say. Matching it to a tileset directory is the domain's
`select_served`; an adapter never does it. A read is uncached and never raises.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from overland_planner.application.ports.probe import Probeable
from overland_planner.domain.roadmap.served_map import ServedId


@runtime_checkable
class ServedMap(Probeable, Protocol):
    def served_id(self) -> ServedId | None: ...

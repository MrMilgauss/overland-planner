"""TourSolver port (brief §6, ADR-015): the optimizer that orders a plan's stops.

Slice 00a declares only the probe contract; `solve()` and incumbent streaming arrive with slice 01b.
"""

from __future__ import annotations

from typing import Protocol

from overland_planner.application.ports.probe import Probeable


class TourSolver(Probeable, Protocol):
    pass

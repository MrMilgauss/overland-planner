"""EventLog port (D54): the only way the application records structured events (brief §12 `Logs`).

An event is a dotted name plus snake_case fields; the adapter adds the timestamp and common fields.
"""

from __future__ import annotations

from typing import Protocol

from overland_planner.application.ports.probe import Probeable


class EventLog(Probeable, Protocol):
    def info(self, event: str, **fields: object) -> None:
        """Record an informational event such as `app.started`."""
        ...

    def warning(self, event: str, **fields: object) -> None:
        """Record an event Marco should act on, such as `security.auth.disabled`."""
        ...

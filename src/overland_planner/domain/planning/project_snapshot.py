"""What planning reads of a project: its read-only view of the catalog (brief §8). Pure domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Anchor = Literal["Start", "End"]


@dataclass(frozen=True)
class ProjectSnapshot:
    start_item_id: str | None = None
    end_item_id: str | None = None

    def missing_anchor(self) -> Anchor | None:
        """The anchor to set first: with both missing, the Start."""
        if self.start_item_id is None:
            return "Start"
        if self.end_item_id is None:
            return "End"
        return None

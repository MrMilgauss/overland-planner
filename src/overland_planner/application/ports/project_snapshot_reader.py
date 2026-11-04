"""ProjectSnapshotReader port (brief §6, §8): planning's read-only view of the catalog, bound to one unit of work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from overland_planner.domain.planning.project_snapshot import ProjectSnapshot


@dataclass(frozen=True)
class ProjectStamp:
    """What a plan run records of the project it was planned from (brief section 8: stale = another revision)."""

    revision: int
    objective: str


class ProjectSnapshotReader(Protocol):
    def read(self, project_id: str) -> ProjectSnapshot | None:
        """The project as planning sees it, or `None` when there is no such project. Items in stable list order."""
        ...

    def stamp(self, project_id: str) -> ProjectStamp:
        """The stamp of a project `read` found, in the same unit of work."""
        ...

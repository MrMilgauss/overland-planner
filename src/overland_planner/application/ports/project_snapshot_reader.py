"""ProjectSnapshotReader port (brief §6, §8): planning's read-only view of the catalog, bound to one unit of work."""

from __future__ import annotations

from typing import Protocol

from overland_planner.domain.planning.project_snapshot import ProjectSnapshot


class ProjectSnapshotReader(Protocol):
    def read(self, project_id: str) -> ProjectSnapshot | None:
        """The project as planning sees it, or `None` when there is no such project."""
        ...

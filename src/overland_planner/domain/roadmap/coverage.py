"""What the loaded road map covers: containment over region outlines and land groups (D302)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.roadmap.outline import Outline


@dataclass(frozen=True)
class RoadMapCoverage:
    """Named region outlines; a region is outside-tested by its real outline, never a bounding box."""

    regions: tuple[tuple[str, Outline], ...]

    def contains(self, point: Coordinate) -> bool:
        return any(outline.contains(point) for _, outline in self.regions)

    def land_groups(self) -> tuple[tuple[str, ...], ...]:
        """Connected components of the 'outlines overlap or touch' relation; computed once per coverage."""
        return self._groups

    @cached_property
    def _groups(self) -> tuple[tuple[str, ...], ...]:
        """Connected components of the 'outlines overlap or touch' relation; names sorted, groups sorted."""
        ordered = sorted(self.regions, key=lambda region: region[0])
        unvisited = list(range(len(ordered)))
        groups: list[tuple[str, ...]] = []
        while unvisited:
            frontier = [unvisited.pop(0)]
            members = list(frontier)
            while frontier:
                current = frontier.pop()
                linked = [i for i in unvisited if ordered[current][1].touches(ordered[i][1])]
                unvisited = [i for i in unvisited if i not in linked]
                frontier.extend(linked)
                members.extend(linked)
            groups.append(tuple(sorted(ordered[i][0] for i in members)))
        return tuple(sorted(groups))

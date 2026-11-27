"""The rules of a road-map change (D305, D315): no overlap, size limit, same day, start window, land groups."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from overland_planner.domain.roadmap.coverage import RoadMapCoverage
from overland_planner.domain.roadmap.estimate import BYTES_PER_GB, Estimate, estimate
from overland_planner.domain.roadmap.outline import Outline

MIN_LEAD = timedelta(minutes=2)
MAX_LEAD = timedelta(days=14)


class Refusal(Exception):
    """A change the rules refuse: a stable code, the owner-facing message, and the figures behind it."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class CatalogRegion:
    key: str
    name: str
    parent: str | None
    bytes: int


@dataclass(frozen=True)
class RegionChoice:
    """The regions the owner wants the road map to hold, against the ones it holds now."""

    catalogue: Mapping[str, CatalogRegion] = field(compare=False)
    served_keys: frozenset[str]
    chosen: frozenset[str]

    def add(self, key: str) -> RegionChoice:
        if key not in self.catalogue:
            raise Refusal("unknown_region", f"{key} is not a known region", key=key)
        others = self.chosen - {key}
        above = sorted(others & set(self._ancestors(key)), key=self._name)
        if above:
            raise Refusal(
                "overlaps_region",
                f"{self._name(key)} is already in the road map as part of {self._name(above[0])}",
            )
        below = sorted((other for other in others if key in self._ancestors(other)), key=self._name)
        if below:
            names = [self._name(other) for other in below]
            listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
            verb = "is" if len(names) == 1 else "are"
            raise Refusal(
                "overlaps_region",
                f"{self._name(key)} contains {listed}, which {verb} already in the road map",
            )
        return RegionChoice(self.catalogue, self.served_keys, self.chosen | {key})

    def remove(self, key: str) -> RegionChoice:
        return RegionChoice(self.catalogue, self.served_keys, self.chosen - {key})

    @property
    def total_bytes(self) -> int:
        return sum(self.catalogue[key].bytes for key in self.chosen)

    @property
    def added(self) -> frozenset[str]:
        return self.chosen - self.served_keys

    @property
    def removed(self) -> frozenset[str]:
        return self.served_keys - self.chosen

    def estimate(self) -> Estimate:
        return estimate(self.total_bytes)

    def check_size(self, max_gb: float) -> None:
        if self.total_bytes > max_gb * BYTES_PER_GB:
            raise Refusal(
                "too_big",
                f"the download would be {self.total_bytes / BYTES_PER_GB:.1f} GB and the limit is {max_gb:g} GB",
                total_bytes=self.total_bytes,
                max_gb=max_gb,
            )

    def land_groups(self, outlines: Mapping[str, Outline]) -> tuple[tuple[str, ...], ...]:
        """Groups of the chosen regions whose outlines overlap or touch; a chosen region without outline is a bug."""
        return RoadMapCoverage(regions=tuple((key, outlines[key]) for key in sorted(self.chosen))).land_groups()

    def _name(self, key: str) -> str:
        return self.catalogue[key].name

    def _ancestors(self, key: str) -> list[str]:
        found: list[str] = []
        parent = self.catalogue[key].parent
        while parent is not None and parent in self.catalogue and parent not in found:
            found.append(parent)
            parent = self.catalogue[parent].parent
        return found


def check_start_window(start: datetime, now: datetime) -> None:
    """A start is acceptable from two minutes to fourteen days after now, both ends included."""
    if not now + MIN_LEAD <= start <= now + MAX_LEAD:
        raise Refusal("bad_start", "the start must be between 2 minutes and 14 days from now")


def check_same_day(start: datetime, directory_names: list[str]) -> None:
    """One rebuild a UTC day: refuse a start whose UTC date names a directory (served, previous or leftover)."""
    day = start.astimezone(UTC).date()
    if day.strftime("%Y%m%d") in directory_names:
        next_midnight = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1)
        raise Refusal("same_day", "a rebuild already ran on that day", next_rebuild_from=next_midnight)

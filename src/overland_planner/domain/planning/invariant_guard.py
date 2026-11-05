"""The guard on every candidate plan (ADR-009 with Amendments 1 and 2, brief section 8). Pure domain.

It only judges: the job reads and hashes the canonical files, hands the evidence over and does the logging. The first
violation found is the result, and it names the rule. Slice 01b runs HC-2, HC-3 without the report, HC-1, HC-5 by
full-sequence hash and the legs against this job's table. Track length against totals, Unconfirmed legs and retraces
arrive with their slices.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import TrackItem
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot, left_at, reached_at
from overland_planner.domain.routing.road_leg import LegTable

INVARIANT_VIOLATION_REASON = "internal_invariant_violation"  # the reason code of ADR-015
GuardCheck = Literal["HC-1", "HC-2", "HC-3", "HC-5", "leg_consistency"]


@dataclass(frozen=True)
class CanonicalFileEvidence:
    """What a track's stored canonical file holds. A file that cannot be read as points has no points and no ends."""

    sha256: str
    point_count: int
    first: Coordinate | None
    last: Coordinate | None


@dataclass(frozen=True)
class GuardViolation:
    check: GuardCheck
    detail: str


class InvariantGuard:
    def __init__(self, snapshot: ProjectSnapshot, legs: LegTable) -> None:
        self._snapshot = snapshot
        self._legs = legs

    def check_order(self, order: Sequence[str]) -> GuardViolation | None:
        """The solver's chosen order, Start to End, before any stop is made of it: unknown ids are named, not raised."""
        return next(self._order_violations(tuple(order)), None)

    def check_plan(
        self, stops: Sequence[PlanStop], files: Mapping[str, CanonicalFileEvidence]
    ) -> GuardViolation | None:
        """The plan about to be stored. `files` holds the evidence by track id; a vanished file has none."""
        return next(self._plan_violations(tuple(stops), files), None)

    def _order_violations(self, order: tuple[str, ...]) -> Iterator[GuardViolation]:
        start, end = self._snapshot.start_item_id, self._snapshot.end_item_id
        if len(order) < 2 or order[0] != start or order[-1] != end:
            yield GuardViolation("HC-2", f"the trip runs {order[:1]} to {order[-1:]}, not {start} to {end}")
        yield from self._items_violations(order[1:-1])

    def _items_violations(self, between: tuple[str, ...]) -> Iterator[GuardViolation]:
        placed = Counter(between)
        wanted = Counter(item.id for item in self._snapshot.visited_items())
        if placed != wanted:
            extra, missing = sorted(placed - wanted), sorted(wanted - placed)
            yield GuardViolation("HC-3", f"not each item once: extra {extra}, missing {missing}")

    def _plan_violations(
        self, stops: tuple[PlanStop, ...], files: Mapping[str, CanonicalFileEvidence]
    ) -> Iterator[GuardViolation]:
        yield from self._order_violations(tuple(stop.item_id for stop in stops))
        yield from self._anchor_kind_violations(stops)
        for stop in stops:
            yield from self._place_violations(stop)
        for stop in stops:
            yield from self._file_violations(stop, files)
        yield from self._leg_violations(stops)

    @staticmethod
    def _anchor_kind_violations(stops: tuple[PlanStop, ...]) -> Iterator[GuardViolation]:
        for anchor in (stops[0], stops[-1]):
            if anchor.kind != "poi":
                yield GuardViolation("HC-2", f"the anchor {anchor.item_id} is not a POI")

    def _place_violations(self, stop: PlanStop) -> Iterator[GuardViolation]:
        expected = PlanStop.of(self._snapshot.item(stop.item_id), stop.leg_km)
        if _place_of(stop) != _place_of(expected):
            yield GuardViolation("HC-1", f"{stop.item_id} is not where and how the snapshot has it")

    def _file_violations(self, stop: PlanStop, files: Mapping[str, CanonicalFileEvidence]) -> Iterator[GuardViolation]:
        item = self._snapshot.item(stop.item_id)
        if not isinstance(item, TrackItem):
            return
        if (stop.point_count, stop.canonical_sha256) != (item.point_count, item.canonical_sha256):
            yield GuardViolation("HC-5", f"track {item.id}: the stop does not name the snapshot's points")
        found = files.get(item.id)
        if found is None:
            yield GuardViolation("HC-5", f"track {item.id}: canonical file v{item.direction_version} is missing")
        if found != CanonicalFileEvidence(item.canonical_sha256, item.point_count, item.entry, item.exit):
            yield GuardViolation("HC-5", f"track {item.id}: canonical file v{item.direction_version} has changed")

    def _leg_violations(self, stops: tuple[PlanStop, ...]) -> Iterator[GuardViolation]:
        # A consistency check between the stops and this job's leg table; it does not prove the table right.
        if stops[0].leg_km is not None:
            yield GuardViolation("leg_consistency", f"the first stop {stops[0].item_id} has a road leg")
        for previous, stop in pairwise(stops):
            road_km = self._road_km(previous, stop)
            if road_km is None or stop.leg_km != road_km:
                yield GuardViolation("leg_consistency", f"the leg into {stop.item_id} is not the road map's")

    def _road_km(self, previous: PlanStop, stop: PlanStop) -> float | None:
        origin = left_at(self._snapshot.item(previous.item_id))
        destination = reached_at(self._snapshot.item(stop.item_id))
        try:
            return self._legs.distance_km(origin, destination)
        except KeyError:
            return None


def _place_of(stop: PlanStop) -> tuple[object, ...]:
    return (stop.kind, stop.location, stop.entry, stop.exit, stop.direction_version)

"""The guard on every candidate plan (ADR-009 with Amendments 1 to 3, brief section 8). Pure domain.

It only judges: the job reads and hashes the canonical files, hands the evidence over and does the logging. The first
violation found is the result, and it names the rule. Slice 01b runs HC-2, HC-3 without the report, HC-1, HC-5 by
full-sequence hash and the legs against this job's table; slice 02 adds check 4's track length and the leg time of
check 5. Slice 03b adds check 6, the retrace form: a retrace row directly after its own track, from its exit to its
entry, Unconfirmed with the product's reason, the track's stored length, no road leg, the hash of the track's reversed
points as read from its file, and only where the retrace rule (`retrace_rule`, the one definition) makes the arc a
retrace; the leg after it is judged from the track's entry (Amendment 3). HC-3 counts the stops other than retraces.
An `unreachable` claim is re-derived from the leg table: arcs by the retrace rule, paths by the guard's own search,
not by the tour model or `reachability`, which made the claim (Amendment 1).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import chain, pairwise
from typing import Literal

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.planning.plan_run import RETRACE_REASON, PlanStop, offroad_of, stored_length_km
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot, road_between
from overland_planner.domain.planning.retrace_rule import ArcKind, arc_kind, second_pass_pair
from overland_planner.domain.routing.road_leg import LegTable, RoadLevel, RoadPair

INVARIANT_VIOLATION_REASON = "internal_invariant_violation"  # the reason code of ADR-015
_NO_ROAD = (None,) * 5  # a retrace row's leg km, seconds, confidence, reason and location: it drives no road
GuardCheck = Literal["HC-1", "HC-2", "HC-3", "HC-5", "leg_consistency", "retrace", "reachability"]


@dataclass(frozen=True)
class CanonicalFileEvidence:
    """What a track's stored canonical file holds. A file that cannot be read as points has no points and no ends.
    `reversed_sha256` is the hash of its points reversed and serialised afresh, for a retraced track only."""

    sha256: str
    point_count: int
    first: Coordinate | None
    last: Coordinate | None
    reversed_sha256: str | None = None


@dataclass(frozen=True)
class GuardViolation:
    check: GuardCheck
    detail: str


class InvariantGuard:
    def __init__(self, snapshot: ProjectSnapshot, legs: LegTable) -> None:
        self._snapshot = snapshot
        self._legs = legs

    def check_order(self, order: Sequence[str]) -> GuardViolation | None:
        """The solver's chosen order, Start to End, before any stop is made of it: unknown ids are named, not raised,
        and so is a consecutive pair no road at any level or retrace joins, which the assembler could not make."""
        chosen = tuple(order)
        return next(chain(self._order_violations(chosen), self._arc_violations(chosen)), None)

    def check_plan(
        self, stops: Sequence[PlanStop], files: Mapping[str, CanonicalFileEvidence]
    ) -> GuardViolation | None:
        """The plan about to be stored. `files` holds the evidence by track id; a vanished file has none."""
        return next(self._plan_violations(tuple(stops), files), None)

    def check_unreachable(self, claimed: Sequence[str]) -> GuardViolation | None:
        """A Failed `unreachable` claim: each item it names must have no path from the Start or none to the End."""
        connected = _Connections(self._snapshot, self._legs).connected_ids()
        wrong = sorted({item_id for item_id in claimed if item_id in connected or not self._is_visited(item_id)})
        if wrong:
            return GuardViolation("reachability", f"claimed unreachable, but an order connects them: {wrong}")
        return None

    def _is_visited(self, item_id: str) -> bool:
        return any(item.id == item_id for item in self._snapshot.visited_items())

    def _order_violations(self, order: tuple[str, ...]) -> Iterator[GuardViolation]:
        start, end = self._snapshot.start_item_id, self._snapshot.end_item_id
        if len(order) < 2 or order[0] != start or order[-1] != end:
            yield GuardViolation("HC-2", f"the trip runs {order[:1]} to {order[-1:]}, not {start} to {end}")
        yield from self._items_violations(order[1:-1])

    def _arc_violations(self, order: tuple[str, ...]) -> Iterator[GuardViolation]:
        """Only for an order that runs Start to End with each item once, so that every id is known."""
        for previous, successor in pairwise(self._snapshot.item(item_id) for item_id in order):
            if _arc_of(previous, successor, self._legs) == "forbidden":
                detail = f"no road at any level or retrace from {previous.id} to {successor.id}"
                yield GuardViolation("leg_consistency", detail)

    def _items_violations(self, between: tuple[str, ...]) -> Iterator[GuardViolation]:
        placed = Counter(between)
        wanted = Counter(item.id for item in self._snapshot.visited_items())
        if placed != wanted:
            extra, missing = sorted(placed - wanted), sorted(wanted - placed)
            yield GuardViolation("HC-3", f"not each item once: extra {extra}, missing {missing}")

    def _plan_violations(
        self, stops: tuple[PlanStop, ...], files: Mapping[str, CanonicalFileEvidence]
    ) -> Iterator[GuardViolation]:
        driven = tuple(stop for stop in stops if stop.kind != "retrace")
        yield from self._order_violations(tuple(stop.item_id for stop in driven))
        yield from self._anchor_kind_violations(stops)
        for stop in driven:
            yield from self._place_violations(stop)
        for stop in driven:
            yield from self._file_violations(stop, files)
        yield from _RetraceForm(self._snapshot, self._legs, files).violations(stops)
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
        stored = CanonicalFileEvidence(item.canonical_sha256, item.point_count, item.entry, item.exit)
        if found is None or replace(found, reversed_sha256=None) != stored:  # the reversed hash is check 6's
            yield GuardViolation("HC-5", f"track {item.id}: canonical file v{item.direction_version} has changed")
        if stop.track_km != stored_length_km(item):
            yield GuardViolation(
                "HC-5", f"track {item.id}: {stop.track_km} km driven, not its stored {item.length_m} m"
            )
        if stop.offroad_s != offroad_of(item, self._snapshot.offroad_speed)[1]:
            yield GuardViolation("HC-5", f"track {item.id}: {stop.offroad_s} s off-road, not its length at the speed")

    def _leg_violations(self, stops: tuple[PlanStop, ...]) -> Iterator[GuardViolation]:
        # A consistency check between the stops and this job's leg table; it does not prove the table right.
        if _leg_of(stops[0]) != (None,) * 4:
            yield GuardViolation("leg_consistency", f"the first stop {stops[0].item_id} has a road leg")
        for previous, stop in pairwise(stops):
            if stop.kind == "retrace":  # not a road leg: check 6 judged it
                continue
            if self._road(previous, stop) != _leg_of(stop):
                yield GuardViolation("leg_consistency", f"the leg into {stop.item_id} is not the road map's")

    def _road(self, previous: PlanStop, stop: PlanStop) -> _Leg | None:
        """The leg's km, seconds, level and reason in this job's table, or None for a pair nobody measured or with no
        road."""
        pair = self._reference_pair(previous, stop)
        if pair is None:
            return None
        try:
            return *self._legs.km_and_s(*pair), self._legs.level(*pair), self._legs.reason(*pair)
        except LookupError:  # a pair nobody measured (KeyError) or with no road at any level (NoRoadError)
            return None

    def _reference_pair(self, previous: PlanStop, stop: PlanStop) -> RoadPair | None:
        """exit(i) -> entry(i+1); after a retrace of t, the retrace rule's entry(t) -> entry(i+1) (Amendment 3)."""
        before, item = self._snapshot.item(previous.item_id), self._snapshot.item(stop.item_id)
        if previous.kind != "retrace":
            return road_between(before, item)
        try:
            return second_pass_pair(before, item, self._legs)
        except KeyError:
            return None


_Leg = tuple[float | None, int | None, RoadLevel | None, str | None]


def _leg_of(stop: PlanStop) -> _Leg:
    """The road leg a stop shows: km, seconds, level and the reason it is Unconfirmed; none at all on the first stop."""
    return stop.leg_km, stop.leg_s, stop.leg_confidence, stop.leg_reason


def _arc_of(previous: CatalogItem, successor: CatalogItem, legs: LegTable) -> ArcKind:
    """The retrace rule's arc; a pair nobody measured joins nothing."""
    try:
        return arc_kind(previous, successor, legs)
    except KeyError:
        return "forbidden"


def _place_of(stop: PlanStop) -> tuple[object, ...]:
    return (stop.kind, stop.location, stop.entry, stop.exit, stop.direction_version)


class _RetraceForm:
    """ADR-009 check 6 on every retrace row of a plan."""

    def __init__(self, snapshot: ProjectSnapshot, legs: LegTable, files: Mapping[str, CanonicalFileEvidence]) -> None:
        self._tracks = {item.id: item for item in snapshot.visited_items() if isinstance(item, TrackItem)}
        self._snapshot = snapshot
        self._legs = legs
        self._files = files

    def violations(self, stops: tuple[PlanStop, ...]) -> Iterator[GuardViolation]:
        for at, stop in enumerate(stops):
            if stop.kind == "retrace" and not self._holds(stops, at):
                yield GuardViolation("retrace", f"the retrace of {stop.item_id} at stop {at} is not its track's")

    def _holds(self, stops: tuple[PlanStop, ...], at: int) -> bool:
        stop = stops[at]
        track = self._tracks.get(stop.item_id)
        if track is None or not 0 < at < len(stops) - 1:
            return False
        before, after = stops[at - 1], stops[at + 1]
        directly_after = (before.kind, before.item_id) == ("track", track.id)
        return directly_after and self._formed(stop, track) and self._is_a_retrace_arc(track, after)

    def _formed(self, stop: PlanStop, track: TrackItem) -> bool:
        found = self._files.get(track.id)
        evidence = None if found is None else found.reversed_sha256
        form = (stop.entry, stop.exit, stop.confidence, stop.reason, stop.track_km, stop.offroad_s, stop.retrace_sha256)
        road = (stop.leg_km, stop.leg_s, stop.leg_confidence, stop.leg_reason, stop.location)
        track_km, offroad_s = offroad_of(track, self._snapshot.offroad_speed)
        wanted = (track.exit, track.entry, "unconfirmed", RETRACE_REASON, track_km, offroad_s, evidence)
        return evidence is not None and form == wanted and road == _NO_ROAD

    def _is_a_retrace_arc(self, track: TrackItem, after: PlanStop) -> bool:
        """Only where no road leaves the exit toward the next stop and one leaves the entry (the retrace rule)."""
        try:
            successor = self._snapshot.item(after.item_id)
        except KeyError:  # an unknown next stop
            return False
        return _arc_of(track, successor, self._legs) == "retrace"


class _Connections:
    """The arcs of the trip by the retrace rule over the leg table, and the items a path runs through Start to End."""

    def __init__(self, snapshot: ProjectSnapshot, legs: LegTable) -> None:
        self._nodes = (snapshot.start(), *snapshot.visited_items(), snapshot.end())
        self._legs = legs

    def connected_ids(self) -> set[str]:
        last = len(self._nodes) - 1
        onward: dict[int, set[int]] = {node: set() for node in range(last + 1)}
        backward: dict[int, set[int]] = {node: set() for node in range(last + 1)}
        for origin in range(last):
            for destination in range(1, last + 1):
                if origin != destination and self._runs(origin, destination):
                    onward[origin].add(destination)
                    backward[destination].add(origin)
        from_start, to_end = _reached(0, onward), _reached(last, backward)
        return {self._nodes[node].id for node in range(1, last) if node in from_start and node in to_end}

    def _runs(self, origin: int, destination: int) -> bool:
        return _arc_of(self._nodes[origin], self._nodes[destination], self._legs) != "forbidden"


def _reached(source: int, onward: Mapping[int, set[int]]) -> set[int]:
    reached, pending = {source}, [source]
    while pending:
        fresh = onward[pending.pop()] - reached
        reached |= fresh
        pending.extend(fresh)
    return reached

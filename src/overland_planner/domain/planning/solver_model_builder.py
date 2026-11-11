"""The tour model of a trip (brief sections 4 and 8). Pure domain.

Node 0 is the Start, the last node the End, one node per Included item between them; a round trip names the same place
at both ends. A track has one node and no reversed variant (HC-1): its arcs leave from its exit and arrive at its entry.
With k items the arcs are the k squared + k required pairs, or the single Start to End pair when k = 0.

Each arc is what the retrace rule says (`arc_kind`, ADR-017): a road from the exit side at its level, a retrace of a
track t back to its entry then the road entry(t) -> entry(j), or no arc. The solver minimises one integer cost per arc
that orders plans lexicographically (FR-5.8, ruled 2026-11-10): fewest Unconfirmed legs, a retrace counting one, then
fewest retraces, then road metres only: W1 * Unconfirmed + W2 * retraces + c, c the arc's road metres (for a retrace,
entry(t) -> entry(j) only, no track length and no penalty). A Confirmed arc costs its plain metres. The real tables
travel with the model, so an order is described with no weight in it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from overland_planner.domain.catalog.item import TrackItem
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot, reached_at, road_between
from overland_planner.domain.planning.retrace_rule import arc_kind, second_pass_pair
from overland_planner.domain.routing.road_leg import LegTable, RoadPair

SINGLE_PHASE = "single_phase"  # W1 > W2 > road metres in one search (decision 18); two-phase is slices 06a/06b


@dataclass(frozen=True)
class TourCounts:
    """An order as the planner reports it (FR-5.8): road metres, Unconfirmed legs (a retrace counting one), retraces.
    No weight is in it, and no retraced track's metres: those are off-road (07-06)."""

    road_m: int
    unconfirmed_legs: int
    retraces: int


@dataclass(frozen=True)
class ArcTables:
    """The real tables per arc, `None` / 0 where no arc runs: road metres (for a retrace arc entry(t) -> entry(j)
    only), Unconfirmed legs and retraces."""

    road_m: tuple[tuple[int | None, ...], ...]
    unconfirmed_legs: tuple[tuple[int, ...], ...]
    retraces: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class LexicographicWeights:
    """W1 > N * (W2 + c_max) and W2 > N * c_max (ADR-016 section 4, N the arcs of a tour), in one search."""

    mode: str
    w1: int
    w2: int


@dataclass(frozen=True)
class TourModel:
    """Plain data for the solver's child process. `arc_m[a][b]` is `None` where no arc runs from node a to node b;
    the child reads only the nodes and `arc_m`. A built model also carries the real tables and the weights; a model
    without them (written by hand) is a plain matrix of metres."""

    node_item_ids: tuple[str, ...]
    start_node: int
    end_node: int
    arc_m: tuple[tuple[int | None, ...], ...]
    real: ArcTables | None = None
    weights: LexicographicWeights | None = None

    def counts_of(self, nodes: Sequence[int]) -> TourCounts | None:
        """The tour through `nodes` read from the real tables; `None` for a plain model or an arc that does not run."""
        if self.real is None:
            return None
        road = [self.real.road_m[a][b] for a, b in pairwise(nodes)]
        if None in road:
            return None
        return TourCounts(
            road_m=sum(metres for metres in road if metres is not None),
            unconfirmed_legs=sum(self.real.unconfirmed_legs[a][b] for a, b in pairwise(nodes)),
            retraces=sum(self.real.retraces[a][b] for a, b in pairwise(nodes)),
        )


@dataclass(frozen=True)
class _Arc:
    road_m: int
    unconfirmed_legs: int
    retraces: int


class SolverModelBuilder:
    def __init__(self, snapshot: ProjectSnapshot) -> None:
        self._nodes = (snapshot.start(), *snapshot.visited_items(), snapshot.end())

    def required_pairs(self) -> tuple[RoadPair, ...]:
        """The road legs the model needs, one per arc."""
        return tuple(self._pair(origin, destination) for origin, destination in self._arcs())

    def retrace_pairs(self, first_pass: LegTable) -> tuple[RoadPair, ...]:
        """The second pass (ADR-017 section 2): entry(t) -> entry(j) for each arc t -> j whose first pair has no road,
        when t may be retraced. Each pair once, in arc order."""
        asked = (
            second_pass_pair(self._nodes[origin], self._nodes[destination], first_pass)
            for origin, destination in self._arcs()
        )
        return tuple(dict.fromkeys(pair for pair in asked if pair is not None))

    def build(self, legs: LegTable) -> TourModel:
        """Each arc through the retrace rule (`arc_kind`); `legs` holds the first pass and any second pass."""
        arcs = {
            (origin, destination): arc
            for origin, destination in self._arcs()
            if (arc := self._arc(origin, destination, legs)) is not None
        }
        weights = _weights(len(self._nodes) - 1, max((arc.road_m for arc in arcs.values()), default=0))
        size = len(self._nodes)

        def table(cell: Callable[[_Arc], int | None], missing: int | None) -> tuple[tuple[Any, ...], ...]:
            return tuple(
                tuple(cell(arcs[a, b]) if (a, b) in arcs else missing for b in range(size)) for a in range(size)
            )

        return TourModel(
            node_item_ids=tuple(item.id for item in self._nodes),
            start_node=0,
            end_node=size - 1,
            arc_m=table(weights.cost, None),
            real=ArcTables(
                road_m=table(lambda arc: arc.road_m, None),
                unconfirmed_legs=table(lambda arc: arc.unconfirmed_legs, 0),
                retraces=table(lambda arc: arc.retraces, 0),
            ),
            weights=weights.published,
        )

    def _arc(self, origin: int, destination: int, legs: LegTable) -> _Arc | None:
        previous, successor = self._nodes[origin], self._nodes[destination]
        kind = arc_kind(previous, successor, legs)
        if kind == "road":
            pair = road_between(previous, successor)
            return _Arc(legs.distance_m(*pair), _unconfirmed(legs, pair), 0)
        if kind == "retrace" and isinstance(previous, TrackItem):  # the rule retraces only a track
            onward = (previous.entry, reached_at(successor))
            return _Arc(legs.distance_m(*onward), 1 + _unconfirmed(legs, onward), 1)
        return None

    def _pair(self, origin: int, destination: int) -> RoadPair:
        return road_between(self._nodes[origin], self._nodes[destination])

    def _arcs(self) -> list[tuple[int, int]]:
        last = len(self._nodes) - 1
        direct = (0, last)
        return [
            (origin, destination)
            for origin in range(last)
            for destination in range(1, last + 1)
            if origin != destination and (last == 1 or (origin, destination) != direct)
        ]


def _unconfirmed(legs: LegTable, pair: RoadPair) -> int:
    return int(legs.level(*pair) == "unconfirmed")


@dataclass(frozen=True)
class _Weighting:
    published: LexicographicWeights

    def cost(self, arc: _Arc) -> int:
        """A Confirmed road arc costs its plain metres, so a Confirmed-only matrix is today's, cell for cell."""
        return self.published.w1 * arc.unconfirmed_legs + self.published.w2 * arc.retraces + arc.road_m


def _weights(arcs_in_a_tour: int, c_max: int) -> _Weighting:
    w2 = (arcs_in_a_tour + 1) * c_max + 1
    w1 = (arcs_in_a_tour + 1) * (w2 + c_max) + 1
    return _Weighting(LexicographicWeights(mode=SINGLE_PHASE, w1=w1, w2=w2))

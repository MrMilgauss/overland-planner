"""The tour model of a trip (brief sections 4 and 8). Pure domain.

Node 0 is the Start, the last node the End, one node per Included item between them; a round trip names the same place
at both ends. A track has one node and no reversed variant (HC-1): its arcs leave from its exit and arrive at its entry.
With k items the arcs are the k squared + k required pairs, or the single Start to End pair when k = 0. Costs are
integer metres.
"""

from __future__ import annotations

from dataclasses import dataclass

from overland_planner.domain.planning.project_snapshot import ProjectSnapshot, road_between
from overland_planner.domain.planning.retrace_rule import second_pass_pair
from overland_planner.domain.routing.road_leg import LegTable, RoadPair


@dataclass(frozen=True)
class TourModel:
    """Plain data for the solver's child process. `arc_m[a][b]` is `None` where no arc runs from node a to node b."""

    node_item_ids: tuple[str, ...]
    start_node: int
    end_node: int
    arc_m: tuple[tuple[int | None, ...], ...]


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
        size = len(self._nodes)
        costs: list[list[int | None]] = [[None] * size for _ in range(size)]
        for origin, destination in self._arcs():
            costs[origin][destination] = legs.distance_m(*self._pair(origin, destination))
        return TourModel(
            node_item_ids=tuple(item.id for item in self._nodes),
            start_node=0,
            end_node=size - 1,
            arc_m=tuple(tuple(row) for row in costs),
        )

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

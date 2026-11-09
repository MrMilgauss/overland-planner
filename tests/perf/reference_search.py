"""The reference plan of I1 from a long search (slice 03-ops, 06-05; US-06a "nearly as good as a long search").

    uv run python -m tests.perf.reference_search                 # 1800 s: the orchestrator's run, committed once
    uv run python -m tests.perf.reference_search --search-s 5 --out /tmp/ref.json

I1's model is built with the planner's SolverModelBuilder on the offline default road map (straight line x 1.3, as
I1's planner-perf runs it) and searched by OR-Tools directly in a child process: PATH_CHEAPEST_ARC then
GUIDED_LOCAL_SEARCH stopped by the time limit `search_s` only, never a solution count, because the product's limits
arrive only in slice 03. The road km of the order found is computed as the planner's totals compute it
(PlanRunAssembler, Totals.of). The result is committed once and is not reproducible by design (time-limited search on
whatever host ran it), which is why the host is recorded.

Written: fixtures/golden/i1-dense.reference-30min.json {road_km, order, search_s, host, solver_identity}.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import platform
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import version
from itertools import pairwise
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from overland_planner.adapters.routing.mock_routing_provider import MockRoutingProvider
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.planning.plan_run import Totals
from overland_planner.domain.planning.plan_run_assembler import PlanRunAssembler
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder, TourModel
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg
from tests.perf.golden_instances import COMMITTED, I1_DENSE, TripData, committed_trip

REFERENCE_KEYS = ("road_km", "order", "search_s", "host", "solver_identity")
DEFAULT_SEARCH_S = 1800
DEFAULT_OUT = COMMITTED / f"{I1_DENSE}.reference-30min.json"
PROJECT_ID = "reference"
CHILD_GRACE_S = 120.0  # model set-up and the first solution before the time limit starts to matter
SEARCH_IDENTITY = f"ortools=={version('ortools')};PATH_CHEAPEST_ARC;GUIDED_LOCAL_SEARCH;time_limit"


@dataclass(frozen=True)
class ReferenceModel:
    """I1 as the planner would plan it: its snapshot, its road legs and the tour model built from them."""

    snapshot: ProjectSnapshot
    legs: LegTable
    model: TourModel
    names: dict[str, str]

    def road_km(self, item_ids: Sequence[str]) -> float:
        """Road km of Start, the items in this order, End: the planner's plan totals."""
        return Totals.of(PlanRunAssembler(self.snapshot, self.legs).assemble(tuple(item_ids))).road_km


def _track(number: int, name: str, points: tuple[tuple[float, float, float], ...]) -> TrackItem:
    coordinates = [Coordinate(lat, lon) for lat, lon, _ in points]
    length_m = math.fsum(a.great_circle_distance_m(b) for a, b in pairwise(coordinates))
    return TrackItem(
        id=f"track-{number:03d}",
        project_id=PROJECT_ID,
        name=name,
        description=None,
        original_sha256="",
        canonical_sha256="",
        direction_version=1,
        point_count=len(points),
        entry=coordinates[0],
        exit=coordinates[-1],
        length_m=length_m,
    )


def _poi(item_id: str, place: tuple[str, float, float]) -> PoiItem:
    name, lat, lon = place
    return PoiItem(id=item_id, project_id=PROJECT_ID, name=name, location=Coordinate(lat, lon))


def i1_model(trip: TripData) -> ReferenceModel:
    items: list[CatalogItem] = [_poi("start", trip.start), _poi("end", trip.end)]
    items += [_track(number, name, points) for number, (name, points) in enumerate(trip.tracks, start=1)]
    items += [_poi(f"poi-{number:03d}", place) for number, place in enumerate(trip.pois, start=1)]
    snapshot = ProjectSnapshot(start_item_id="start", end_item_id="end", items=tuple(items))
    builder = SolverModelBuilder(snapshot)
    road_map = MockRoutingProvider()
    legs = []
    for origin, destination in builder.required_pairs():
        ((measure,),) = road_map.matrix([origin], [destination])
        legs.append(RoadLeg(origin, destination, measure.distance_m, measure.duration_s))
    table = LegTable(legs)
    return ReferenceModel(snapshot, table, builder.build(table), {item.id: item.name for item in items})


def _search_child(answer: Connection, model: TourModel, search_s: float) -> None:
    """Child entry point: OR-Tools imported here only; sends the node order, Start first and End last."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    size = len(model.arc_m)
    manager = pywrapcp.RoutingIndexManager(size, 1, [model.start_node], [model.end_node])
    routing = pywrapcp.RoutingModel(manager)
    costs = [[0 if cost is None else cost for cost in row] for row in model.arc_m]
    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitMatrix(costs))
    for origin in range(size):
        for destination in range(size):
            if origin in (destination, model.end_node) or destination == model.start_node:
                continue
            if model.arc_m[origin][destination] is None:
                target = routing.End(0) if destination == model.end_node else manager.NodeToIndex(destination)
                routing.NextVar(manager.NodeToIndex(origin)).RemoveValue(target)
    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    parameters.time_limit.FromMilliseconds(round(search_s * 1000))
    solution = routing.SolveWithParameters(parameters)
    order: list[int] = []
    if solution is not None:
        index = routing.Start(0)
        while not routing.IsEnd(index):
            order.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))
        order.append(manager.IndexToNode(index))
    answer.send(tuple(order))
    answer.close()


def search(model: TourModel, search_s: float) -> tuple[int, ...]:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(target=_search_child, args=(sender, model, search_s), name="reference-search", daemon=True)
    child.start()
    sender.close()
    try:
        if not receiver.poll(search_s + CHILD_GRACE_S):
            raise RuntimeError(f"the reference search did not answer within {search_s + CHILD_GRACE_S:.0f} s")
        nodes: tuple[int, ...] = receiver.recv()
    finally:
        receiver.close()
        child.join(5)
        if child.is_alive():
            child.kill()
            child.join()
    if sorted(nodes) != list(range(len(model.node_item_ids))):
        raise RuntimeError(f"the reference search returned no complete tour: {nodes}")
    return nodes


def reference(trip: TripData, search_s: float) -> dict[str, Any]:
    built = i1_model(trip)
    ids = [built.model.node_item_ids[node] for node in search(built.model, search_s)]
    return {
        "road_km": built.road_km(ids[1:-1]),
        "order": [built.names[item_id] for item_id in ids],
        "search_s": search_s,
        "host": f"{platform.node()} ({platform.system()} {platform.machine()}, python {platform.python_version()})",
        "solver_identity": SEARCH_IDENTITY,
    }


def write_reference(out: Path, *, search_s: float = DEFAULT_SEARCH_S) -> dict[str, Any]:
    document = reference(committed_trip(COMMITTED / f"{I1_DENSE}.json"), search_s)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.perf.reference_search", description=__doc__.split("\n")[0])
    parser.add_argument("--search-s", type=float, default=DEFAULT_SEARCH_S)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    arguments = parser.parse_args(argv)
    search_s = int(arguments.search_s) if arguments.search_s.is_integer() else arguments.search_s
    document = write_reference(arguments.out, search_s=search_s)
    print(f"reference: {document['road_km']:.1f} road km after {search_s} s on {document['host']} -> {arguments.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

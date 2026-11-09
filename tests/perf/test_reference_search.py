"""The 30-minute reference tool (06-05): I1's model searched by OR-Tools for a fixed time, road km as the planner's
totals compute it. Unit-tested with a 5 s search; the 30-minute run is the orchestrator's."""

from __future__ import annotations

import json
import math
from itertools import pairwise
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.common.state_delta import assert_state_delta, set_to
from tests.perf.golden_instances import COMMITTED, committed_trip
from tests.perf.reference_search import REFERENCE_KEYS, i1_model, write_reference

TRIP = committed_trip(COMMITTED / "i1-dense.json")
MODEL = i1_model(TRIP)
ITEM_IDS = MODEL.model.node_item_ids[1:-1]


def objective_km(item_ids: tuple[str, ...]) -> float:
    """Oracle: the search's own objective, the model's arc metres along Start, the items in order, End."""
    node = {item_id: index for index, item_id in enumerate(MODEL.model.node_item_ids)}
    nodes = [MODEL.model.start_node, *(node[i] for i in item_ids), MODEL.model.end_node]
    metres = [MODEL.model.arc_m[a][b] for a, b in pairwise(nodes)]
    assert None not in metres, "every consecutive pair of a tour is an arc of the model"
    return math.fsum(m for m in metres if m is not None) / 1000


@given(order=st.permutations(ITEM_IDS))
@settings(max_examples=50, deadline=None)
def test_road_km_of_any_order_is_the_objective_the_search_minimises(order: list[str]) -> None:
    before = {"road_km": None}

    after = {"road_km": round(MODEL.road_km(tuple(order)), 6)}

    assert_state_delta(
        before,
        after,
        universe={"road_km"},
        expected={"road_km": set_to(round(objective_km(tuple(order)), 6))},
        strict=True,
    )


@pytest.mark.solver_child
def test_a_short_search_writes_a_complete_reference_better_than_the_listed_order(tmp_path: Path) -> None:
    # bypass: a real 5 s OR-Tools search is expensive and not deterministic; one run checks the written reference.
    out = tmp_path / "i1-dense.reference-30min.json"

    write_reference(out, search_s=5)

    document = json.loads(out.read_text(encoding="utf-8"))
    stops = [TRIP.start[0], *(n for n, _ in TRIP.tracks), *(n for n, *_ in TRIP.pois), TRIP.end[0]]
    by_name = {MODEL.names[item_id]: item_id for item_id in MODEL.model.node_item_ids}
    assert set(document) == set(REFERENCE_KEYS)
    assert document["search_s"] == 5 and document["host"] and document["solver_identity"].startswith("ortools==")
    assert (document["order"][0], document["order"][-1]) == (TRIP.start[0], TRIP.end[0])
    assert sorted(document["order"]) == sorted(stops)
    reference_ids = tuple(by_name[name] for name in document["order"][1:-1])
    assert document["road_km"] == pytest.approx(objective_km(reference_ids), abs=1e-6)
    assert document["road_km"] < objective_km(ITEM_IDS), "a search beats the order the fixture lists"

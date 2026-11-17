"""The golden model pin (slice 03b, 07-01; D223): the sha256 of the solver cost matrix the production builder gives
for I1 and I2, recorded on the unchanged tip of 06-13. The golden order takes minutes and says nothing about why it
moved; this hash is instant and fails on the exact change that could move it (a Confirmed arc cost, the node order,
a scaling, an extra arc).

    uv run python -m tests.perf.test_golden_model_pin record   # rewrite golden_model_pins.json from the current code

Recording is for the unchanged tip only; a mismatch later is reported to the orchestrator, never recorded over.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.adapters.routing.mock_routing_provider import MockRoutingProvider, read_road_map
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder, TourModel
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg
from tests.perf.golden_instances import COMMITTED, I1_DENSE, I2_SPARSE, committed_trip
from tests.perf.reference_search import i1_model

PINS = Path(__file__).with_name("golden_model_pins.json")
ROAD_MAPS = {I1_DENSE: None, I2_SPARSE: "i2-sparse.road-map.yaml"}


def model_sha256(model: TourModel) -> str:
    """sha256 of the nodes in model order and the arc cost matrix: JSON with sorted keys, None as null."""
    document = {"nodes": list(model.node_item_ids), "arc_m": [list(row) for row in model.arc_m]}
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def production_model(kind: str) -> TourModel:
    """The TourModel the production SolverModelBuilder gives through the legs of the instance's offline road map."""
    trip = committed_trip(COMMITTED / f"{kind}.json")
    snapshot = i1_model(trip).snapshot
    script = ROAD_MAPS[kind]
    road_map = MockRoutingProvider(script=read_road_map(COMMITTED / script)) if script else MockRoutingProvider()
    builder = SolverModelBuilder(snapshot)
    legs = []
    for origin, destination in builder.required_pairs():
        ((measure,),) = road_map.matrix([origin], [destination])
        assert measure is not None, "the pinned instances have a road for every required pair"
        legs.append(RoadLeg(origin, destination, measure.distance_m, measure.duration_s))
    return builder.build(LegTable(legs))


def weights_of(model: TourModel) -> dict[str, int]:
    assert model.weights is not None
    return {"w1": model.weights.w1, "w2": model.weights.w2}


def record() -> dict[str, str]:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    pins = {
        "commit": commit,
        **{kind: model_sha256(production_model(kind)) for kind in ROAD_MAPS},
        "weights": {kind: weights_of(production_model(kind)) for kind in ROAD_MAPS},
    }
    PINS.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")
    return pins


def longer_by_one_metre(model: TourModel) -> TourModel:
    rows = [list(row) for row in model.arc_m]
    row, column = next((r, c) for r, line in enumerate(rows) for c, cost in enumerate(line) if cost is not None)
    rows[row][column] = (rows[row][column] or 0) + 1
    return replace(model, arc_m=tuple(tuple(line) for line in rows))


def scaled(model: TourModel, factor: int) -> TourModel:
    arc_m = tuple(tuple(None if cost is None else cost * factor for cost in row) for row in model.arc_m)
    return replace(model, arc_m=arc_m)


def test_the_production_models_of_i1_and_i2_match_their_recorded_pins() -> None:
    # bypass: the two committed instances against their recorded hashes; the hash's sensitivity is the properties below.
    pins = json.loads(PINS.read_text(encoding="utf-8"))

    actual = {kind: model_sha256(production_model(kind)) for kind in ROAD_MAPS}

    assert actual == {kind: pins[kind] for kind in ROAD_MAPS}, (
        f"the solver model moved since {pins['commit']}: report to the orchestrator, never re-record or bless"
    )


def test_the_production_models_of_i1_and_i2_keep_their_recorded_weights() -> None:
    # bypass: W1 and W2 of the two committed instances, recorded on the unchanged code before the objective existed.
    pins = json.loads(PINS.read_text(encoding="utf-8"))

    actual = {kind: weights_of(production_model(kind)) for kind in ROAD_MAPS}

    assert actual == pins["weights"], "the weights moved: report to the orchestrator, never re-record or bless"


def test_a_perturbed_production_model_does_not_match_its_pin() -> None:
    # bypass: proves the pin can fail on the real instances: one arc 1 m longer, and the whole matrix doubled.
    pins = json.loads(PINS.read_text(encoding="utf-8"))

    for kind in ROAD_MAPS:
        model = production_model(kind)
        assert model_sha256(model) == pins[kind]
        assert model_sha256(longer_by_one_metre(model)) != pins[kind]
        assert model_sha256(scaled(model, 2)) != pins[kind]


@st.composite
def tour_models(draw: st.DrawFn) -> TourModel:
    size = draw(st.integers(min_value=2, max_value=6))
    cost = st.one_of(st.none(), st.integers(min_value=1, max_value=10_000_000))
    arc_m = tuple(tuple(draw(cost) for _ in range(size)) for _ in range(size))
    return TourModel(tuple(f"n{i}" for i in range(size)), 0, size - 1, arc_m)


@given(model=tour_models(), data=st.data())
@settings(max_examples=100, deadline=None)
def test_the_hash_moves_with_any_single_cell_and_stays_for_an_equal_matrix(
    model: TourModel, data: st.DataObject
) -> None:
    size = len(model.arc_m)
    row, column = data.draw(st.integers(0, size - 1)), data.draw(st.integers(0, size - 1))
    other = data.draw(st.one_of(st.none(), st.integers(1, 10_000_000)).filter(lambda v: v != model.arc_m[row][column]))
    rows = [list(line) for line in model.arc_m]
    rows[row][column] = other

    changed = replace(model, arc_m=tuple(tuple(line) for line in rows))

    assert model_sha256(model) == model_sha256(replace(model))
    assert model_sha256(changed) != model_sha256(model)


@given(model=tour_models(), factor=st.integers(min_value=2, max_value=5))
@settings(max_examples=100, deadline=None)
def test_the_hash_moves_with_the_node_order_and_with_a_scaling(model: TourModel, factor: int) -> None:
    swapped = replace(model, node_item_ids=tuple(reversed(model.node_item_ids)))
    has_cost = any(cost is not None for row in model.arc_m for cost in row)

    assert model_sha256(swapped) != model_sha256(model)
    assert not has_cost or model_sha256(scaled(model, factor)) != model_sha256(model)


if __name__ == "__main__":
    if sys.argv[1:] != ["record"]:
        sys.exit(__doc__)
    print(json.dumps(record(), indent=2))

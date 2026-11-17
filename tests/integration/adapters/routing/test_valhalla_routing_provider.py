"""The Valhalla adapter (ADR-013) against the recorded Valhalla 3.9.1 answers, replayed through respx, and against a
scripted engine behind the httpx transport seam. No live engine, no network.

Expected figures come from the recordings and the written rules (km to whole metres, whole seconds), not from the
adapter's own arithmetic. The batching is one property over question sizes: every cell answered once, no question
above the engine's limit, never more than two in flight, also when two matrix questions are asked at the same time.
"""

from __future__ import annotations

import threading
from typing import Any

import httpx
import pytest
import respx
from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.adapters.routing.valhalla_routing_provider import ValhallaRoutingProvider
from overland_planner.application.ports.routing_provider import ProviderRejected
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import RoadMeasure
from tests.common.state_delta import assert_state_delta, set_to
from tests.contract.routing_port.recordings import REPLAY_URL, BatchLimitedEngine, recording

SNAP_M = 250


def provider(
    transport: httpx.BaseTransport | None = None, *, max_matrix_pairs: int = 2500, concurrency: int = 2
) -> ValhallaRoutingProvider:
    return ValhallaRoutingProvider(
        REPLAY_URL,
        expected_version="3.9.1",
        max_matrix_pairs=max_matrix_pairs,
        concurrency=concurrency,
        snap_m=SNAP_M,
        transport=transport,
    )


def places(request_places: list[dict[str, Any]]) -> list[Coordinate]:
    return [Coordinate(p["lat"], p["lon"]) for p in request_places]


def replay(*names: str) -> respx.MockRouter:
    router = respx.mock(base_url=REPLAY_URL, assert_all_called=False)
    router.get("/status").respond(json=recording("status")["response"])
    for name in names:
        recorded = recording(name)
        router.post(recorded["endpoint"], json=recorded["request"]).respond(
            recorded["status"], json=recorded["response"]
        )
    return router


def test_identity_is_read_from_status_on_first_use_and_names_the_4x4_profile() -> None:
    with replay() as router:
        adapter = provider()
        before = router.calls.call_count
        identity = (adapter.provider_id, adapter.provider_id, adapter.profile)

        assert_state_delta(
            {"status_calls": before, "identity": None},
            {"status_calls": router.calls.call_count, "identity": identity},
            universe={"status_calls", "identity"},
            expected={
                "status_calls": set_to(1),
                "identity": set_to(("valhalla:3.9.1:1793560782", "valhalla:3.9.1:1793560782", "4x4.v1")),
            },
            strict=True,
        )


def test_identity_is_read_again_after_every_probe() -> None:
    served = {"tileset_last_modified": 1793560782}

    def engine(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": "3.9.1", **served})

    adapter = provider(httpx.MockTransport(engine))
    first = adapter.provider_id
    served["tileset_last_modified"] = 1800000000
    unchanged_until_probed = adapter.provider_id
    outcome = adapter.probe().outcome

    assert (first, unchanged_until_probed, outcome, adapter.provider_id) == (
        "valhalla:3.9.1:1793560782",
        "valhalla:3.9.1:1793560782",
        "ok",
        "valhalla:3.9.1:1800000000",
    )


def test_a_probe_of_another_engine_version_is_fatal() -> None:
    def engine(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": "3.10.0", "tileset_last_modified": 1})

    result = provider(httpx.MockTransport(engine)).probe()

    assert (result.outcome, result.reason is not None and "3.10.0" in result.reason) == ("fatal", True)


def test_a_matrix_question_is_the_recorded_one_and_each_cell_reads_to_whole_metres_and_seconds() -> None:
    recorded = recording("matrix_confirmed_5x5")
    request = recorded["request"]
    with replay("matrix_confirmed_5x5"):  # an unrecorded request shape is not answered: respx raises
        answer = provider().matrix(places(request["sources"]), places(request["targets"]))

    cells = recorded["response"]["sources_to_targets"]
    assert [list(row) for row in answer] == [
        [None if cell["time"] is None else RoadMeasure(round(cell["distance"] * 1000), cell["time"]) for cell in row]
        for row in cells
    ]
    assert answer[0][0] == RoadMeasure(distance_m=124374, duration_s=6896)


def test_a_null_cell_is_no_road_and_leaves_the_other_cells_alone() -> None:
    recorded = recording("matrix_confirmed_with_island_null_row")
    request = recorded["request"]
    with replay("matrix_confirmed_with_island_null_row"):
        answer = provider().matrix(places(request["sources"]), places(request["targets"]))

    assert [list(row) for row in answer] == [
        [RoadMeasure(68613, 4058), RoadMeasure(112134, 6140)],
        [None, None],
    ]


@pytest.mark.parametrize(
    ("source", "target", "cell", "expected"),
    [
        (Coordinate(45.0, 7.0), Coordinate(45.00001, 7.0), {"time": 0, "distance": 0.0004}, RoadMeasure(1, 1)),
        (Coordinate(45.0, 7.0), Coordinate(45.0, 7.0), {"time": 0, "distance": 0.0}, RoadMeasure(0, 0)),
    ],
)
def test_distinct_points_are_at_least_one_metre_and_one_second_apart_and_identical_points_nothing(
    source: Coordinate, target: Coordinate, cell: dict[str, Any], expected: RoadMeasure
) -> None:
    def engine(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sources_to_targets": [[{"from_index": 0, "to_index": 0, **cell}]]})

    assert provider(httpx.MockTransport(engine)).matrix([source], [target]) == [[expected]]


def test_a_refusal_of_the_engine_is_a_rejection_that_names_its_code() -> None:
    sources = [Coordinate(44.0 + i / 100, 7.0) for i in range(51)]
    targets = [Coordinate(44.0, 7.5 + j / 100) for j in range(50)]  # 2,550 cells above the engine's 2,500
    engine = BatchLimitedEngine(2500, sources, targets)

    with pytest.raises(ProviderRejected, match="150"):
        provider(httpx.MockTransport(engine), max_matrix_pairs=3000).matrix(sources, targets)


@given(
    n_sources=st.integers(1, 7),
    n_targets=st.integers(1, 7),
    limit=st.integers(1, 12),
)
@settings(max_examples=40, deadline=None)
def test_a_batch_is_asked_in_questions_within_the_limit_two_at_a_time_and_every_cell_is_answered_once(
    n_sources: int, n_targets: int, limit: int
) -> None:
    sources = [Coordinate(44.0 + i / 100, 7.0) for i in range(n_sources)]
    targets = [Coordinate(44.0, 7.5 + j / 100) for j in range(n_targets)]
    engine = BatchLimitedEngine(limit, sources, targets, pause_s=0.002)
    adapter = provider(httpx.MockTransport(engine), max_matrix_pairs=limit)
    answers: list[Any] = []
    asker = threading.Thread(target=lambda: answers.append(adapter.matrix(sources, targets)))
    asker.start()  # a second question at the same time shares the same two places at the engine
    answers.append(adapter.matrix(sources, targets))
    asker.join()

    expected = [[RoadMeasure(*BatchLimitedEngine.measure(i, j)) for j in range(n_targets)] for i in range(n_sources)]
    assert [[list(row) for row in answer] for answer in answers] == [expected, expected]
    assert (engine.refusals, max(engine.question_sizes) <= limit, sum(engine.question_sizes)) == (
        0,
        True,
        2 * n_sources * n_targets,
    )
    assert engine.most_in_flight <= 2

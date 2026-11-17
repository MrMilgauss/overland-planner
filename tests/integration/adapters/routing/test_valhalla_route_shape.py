"""The Valhalla adapter's `route_shape` (ADR-007 Amendment 2, D252) against the recorded Valhalla 3.9.1 answers,
replayed through respx, and against a scripted engine behind the httpx transport seam. No live engine, no network.

Expected figures come from the recordings and the written rules, not from the adapter's own arithmetic.
Test Budget: 5 behaviors (the recorded /route request is posted and its polyline6 shape decoded; no path and no
suitable edges answer the straight line, not available; a failure that may pass is retried with the matrix's waits and a
refusal is a typed rejection; never more than two calls in flight; identical points ask nothing) x 2 = 10; 6 used.
"""

from __future__ import annotations

import threading
import time

import httpx
import pytest
import respx
from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.application.ports.routing_provider import (
    ProviderRejected,
    ProviderUnavailable,
    ProviderUnreachable,
)
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_shape import RoadShape
from tests.contract.routing_port.recordings import REPLAY_URL, ScriptedEngine, recording
from tests.integration.adapters.routing.test_valhalla_routing_provider import JITTER_S, RETRY_WAITS, provider

TORINO = Coordinate(45.0703, 7.6869)
SUSA = Coordinate(45.137, 7.05)
SNAP_M = 250


def _located(request: dict[str, list[dict[str, float]]]) -> tuple[Coordinate, Coordinate]:
    origin, destination = request["locations"]
    return Coordinate(origin["lat"], origin["lon"]), Coordinate(destination["lat"], destination["lon"])


def test_the_recorded_route_request_is_posted_and_its_shape_decoded_between_the_two_places() -> None:
    recorded = recording("route_torino_susa_4x4v1")
    router = respx.mock(base_url=REPLAY_URL, assert_all_called=False)
    router.get("/status").respond(json=recording("status")["response"])
    route = router.post("/route", json=recorded["request"]).respond(recorded["status"], json=recorded["response"])
    chunks_ended = sum(1 for c in recorded["response"]["trip"]["legs"][0]["shape"] if ord(c) - 63 < 0x20)

    with router:  # an unrecorded request shape is not answered: respx raises
        shape = provider().route_shape(TORINO, SUSA)
        asked = route.call_count  # respx forgets its calls on leaving the context

    assert asked == 1
    assert shape.available
    assert len(shape.points) == chunks_ended // 2
    assert shape.points[0].great_circle_distance_m(TORINO) <= SNAP_M
    assert shape.points[-1].great_circle_distance_m(SUSA) <= SNAP_M


@pytest.mark.parametrize("name", ["route_442_island_source", "route_171_near_point_cutoff250"])
def test_no_path_and_no_suitable_edges_answer_the_straight_line_not_available(name: str) -> None:
    recorded = recording(name)
    origin, destination = _located(recorded["request"])
    engine = ScriptedEngine(route=[httpx.Response(recorded["status"], json=recorded["response"])])

    shape = provider(httpx.MockTransport(engine)).route_shape(origin, destination)

    assert shape == RoadShape((origin, destination), available=False)
    assert len(engine.asked("route")) == 1


@given(failures=st.lists(st.sampled_from(["connect", "timeout", "server"]), min_size=0, max_size=4))
@settings(max_examples=30, deadline=None)
def test_a_failure_that_may_pass_is_retried_with_the_matrix_waits_and_the_last_names_the_error(
    failures: list[str],
) -> None:
    recorded = recording("route_torino_susa_4x4v1")
    steps = {
        "connect": lambda: httpx.ConnectError("refused"),
        "timeout": lambda: httpx.ReadTimeout("no answer"),
        "server": lambda: httpx.Response(503, text="busy"),
    }
    engine = ScriptedEngine(
        route=[*(steps[kind]() for kind in failures), httpx.Response(200, json=recorded["response"])]
    )
    waits: list[float] = []
    calls_allowed = 1 + len(RETRY_WAITS)  # the first call and three retries
    outcome: object
    try:
        outcome = provider(httpx.MockTransport(engine), waits=waits).route_shape(TORINO, SUSA).available
    except (ProviderUnreachable, ProviderUnavailable) as failure:
        outcome = type(failure)

    made = min(len(failures) + 1, calls_allowed)
    exhausted = len(failures) >= calls_allowed
    last = {"connect": ProviderUnreachable, "timeout": ProviderUnreachable, "server": ProviderUnavailable}
    assert (outcome, len(engine.asked("route")), waits) == (
        last[failures[calls_allowed - 1]] if exhausted else True,
        made,
        [base + JITTER_S for base in RETRY_WAITS[: made - 1]],
    )


def test_a_refusal_other_than_no_path_is_a_rejection_that_names_its_code_and_is_not_retried() -> None:
    refusal = httpx.Response(400, json={"error_code": 154, "error": "Path distance exceeds the max distance limit"})
    engine = ScriptedEngine(route=[refusal])

    with pytest.raises(ProviderRejected, match="154"):
        provider(httpx.MockTransport(engine)).route_shape(TORINO, SUSA)

    assert len(engine.asked("route")) == 1


def test_identical_points_are_a_one_point_shape_and_ask_the_engine_nothing() -> None:
    engine = ScriptedEngine(route=[httpx.Response(500)])

    shape = provider(httpx.MockTransport(engine)).route_shape(TORINO, TORINO)

    assert (shape, engine.asked("route")) == (RoadShape((TORINO,), available=True), [])


def test_shapes_asked_at_the_same_time_share_the_two_calls_of_the_road_map() -> None:
    recorded = recording("route_torino_susa_4x4v1")
    lock, in_flight, most = threading.Lock(), [0], [0]

    def engine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json=recording("status")["response"])
        with lock:
            in_flight[0] += 1
            most[0] = max(most[0], in_flight[0])
        time.sleep(0.01)
        with lock:
            in_flight[0] -= 1
        return httpx.Response(200, json=recorded["response"])

    adapter = provider(httpx.MockTransport(engine), concurrency=2)
    askers = [threading.Thread(target=lambda: adapter.route_shape(TORINO, SUSA)) for _ in range(6)]
    for asker in askers:
        asker.start()
    for asker in askers:
        asker.join()

    assert 1 <= most[0] <= 2

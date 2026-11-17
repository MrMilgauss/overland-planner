"""The fault catalogue of the routing adapter (brief section 6, ADR-011), one gold test per row: what the engine does,
and the typed outcome the planner gets. None of them is ever a missing road (`None`)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from overland_planner.adapters.routing.valhalla_routing_provider import ValhallaRoutingProvider
from overland_planner.application.ports.routing_provider import (
    ProviderRejected,
    ProviderUnavailable,
    ProviderUnreachable,
)
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import RoadMeasure
from tests.contract.routing_port.recordings import REPLAY_URL, ScriptedEngine

TORINO = Coordinate(45.0703, 7.6869)
SUSA = Coordinate(45.1370, 7.0500)


def ask(
    *steps: httpx.Response | Exception, status: httpx.Response | None = None
) -> tuple[ScriptedEngine, list[list[Any]]]:
    """The engine asked and what the adapter answered."""
    engine = ScriptedEngine(sources_to_targets=list(steps), **({"status": [status]} if status else {}))
    answer = ValhallaRoutingProvider(
        REPLAY_URL,
        expected_version="3.9.1",
        max_matrix_pairs=2500,
        concurrency=2,
        snap_m=250,
        transport=httpx.MockTransport(engine),
        sleep=lambda seconds: None,
        jitter=lambda: 0.0,
    ).matrix([TORINO], [SUSA])
    return engine, [list(row) for row in answer]


def cell(**measure: Any) -> httpx.Response:
    return httpx.Response(200, json={"sources_to_targets": [[{"from_index": 0, "to_index": 0, **measure}]]})


def test_connection_refused_is_unreachable() -> None:
    with pytest.raises(ProviderUnreachable):
        ask(httpx.ConnectError("refused"))


def test_a_timeout_is_unreachable() -> None:
    with pytest.raises(ProviderUnreachable):
        ask(httpx.ReadTimeout("slow"))


def test_a_server_error_then_success_is_the_answer() -> None:
    engine, answer = ask(httpx.Response(503, text="busy"), cell(time=3342, distance=56.099))

    assert (len(engine.asked("sources_to_targets")), answer) == (2, [[RoadMeasure(56099, 3342)]])


def test_a_persistent_server_error_is_unavailable_after_the_retries() -> None:
    with pytest.raises(ProviderUnavailable):
        ask(httpx.Response(500, text="broken"))


def test_error_171_for_one_location_is_a_rejection_naming_171() -> None:
    with pytest.raises(ProviderRejected, match="171"):
        ask(httpx.Response(400, json={"error_code": 171, "error": "No suitable edges near location"}))


def test_error_442_is_a_rejection_naming_442() -> None:
    with pytest.raises(ProviderRejected, match="442"):
        ask(httpx.Response(400, json={"error_code": 442, "error": "No path could be found for input"}))


def test_a_null_cell_is_no_road_asked_and_answered() -> None:
    # bypass: the one row where None is right; the engine asked and found no road at any level (allow_second_pass)
    engine = ScriptedEngine(sources_to_targets=[cell(time=None, distance=None)])
    answer = ValhallaRoutingProvider(
        REPLAY_URL,
        expected_version="3.9.1",
        max_matrix_pairs=2500,
        concurrency=2,
        snap_m=250,
        transport=httpx.MockTransport(engine),
    ).matrix([TORINO], [SUSA])

    assert [list(row) for row in answer] == [[None]]


@pytest.mark.parametrize("body", [{"unexpected": 1}, {"sources_to_targets": [[]]}, {"sources_to_targets": "x"}])
def test_a_wrong_shape_is_a_rejection_not_a_missing_road(body: dict[str, Any]) -> None:
    with pytest.raises(ProviderRejected):
        ask(httpx.Response(200, json=body))


def test_zero_distance_for_distinct_points_is_one_metre_and_one_second() -> None:
    engine = ScriptedEngine(sources_to_targets=[cell(time=0, distance=0.0)])
    answer = ValhallaRoutingProvider(
        REPLAY_URL,
        expected_version="3.9.1",
        max_matrix_pairs=2500,
        concurrency=2,
        snap_m=250,
        transport=httpx.MockTransport(engine),
    ).matrix([TORINO], [SUSA])

    assert [list(row) for row in answer] == [[RoadMeasure(1, 1)]]


def test_a_version_mismatch_is_unavailable_and_asks_no_question() -> None:
    engine = ScriptedEngine(
        sources_to_targets=[cell(time=1, distance=1.0)],
        status=[httpx.Response(200, json={"version": "3.10.0", "tileset_last_modified": 1})],
    )
    adapter = ValhallaRoutingProvider(
        REPLAY_URL,
        expected_version="3.9.1",
        max_matrix_pairs=2500,
        concurrency=2,
        snap_m=250,
        transport=httpx.MockTransport(engine),
    )

    with pytest.raises(ProviderUnavailable, match=r"3\.10\.0"):
        _ = adapter.provider_id
    assert engine.asked("sources_to_targets") == []

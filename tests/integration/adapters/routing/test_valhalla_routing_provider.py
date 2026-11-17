"""The Valhalla adapter (ADR-013) against the recorded Valhalla 3.9.1 answers, replayed through respx, and against a
scripted engine behind the httpx transport seam. No live engine, no network.

Expected figures come from the recordings and the written rules (km to whole metres, whole seconds), not from the
adapter's own arithmetic. The batching is one property over question sizes: every cell answered once, no question
above the engine's limit, never more than two in flight, also when two matrix questions are asked at the same time.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import httpx
import pytest
import respx
from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.adapters.routing.valhalla_routing_provider import ValhallaRoutingProvider
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.routing_provider import (
    ProviderRejected,
    ProviderUnavailable,
    ProviderUnreachable,
)
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import OffNetwork, RoadMeasure
from tests.common.state_delta import assert_state_delta, set_to
from tests.contract.routing_port.recordings import REPLAY_URL, BatchLimitedEngine, ScriptedEngine, recording

SNAP_M = 250
JITTER_S = 0.1
TORINO = Coordinate(45.0703, 7.6869)
SUSA = Coordinate(45.1370, 7.0500)


def provider(
    transport: httpx.BaseTransport | None = None,
    *,
    max_matrix_pairs: int = 2500,
    concurrency: int = 2,
    waits: list[float] | None = None,
) -> ValhallaRoutingProvider:
    return ValhallaRoutingProvider(
        REPLAY_URL,
        sleep=waits.append if waits is not None else (lambda seconds: None),
        jitter=lambda: JITTER_S,
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


def test_provider_id_of_another_engine_version_is_unavailable() -> None:
    engine = ScriptedEngine(status=[httpx.Response(200, json={"version": "3.10.0", "tileset_last_modified": 1})])

    with pytest.raises(ProviderUnavailable, match=r"3\.10\.0"):
        _ = provider(httpx.MockTransport(engine)).provider_id


def test_identity_is_read_again_after_every_probe() -> None:
    served = {"tileset_last_modified": 1793560782}

    def engine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sources_to_targets":
            return httpx.Response(200, json=GOOD_GRID)
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


# --- step 09-03: retries, typed errors, off-network places, probe ---------------------------------------------------

ONE_CELL = {"sources_to_targets": [[{"from_index": 0, "to_index": 0, "time": 3342, "distance": 56.099}]]}
RETRY_WAITS = [0.5, 1.0, 2.0]
FAILURES = {
    "connect": lambda: httpx.ConnectError("refused"),
    "timeout": lambda: httpx.ReadTimeout("no answer"),
    "server": lambda: httpx.Response(503, text="busy"),
}
RAISED = {"connect": ProviderUnreachable, "timeout": ProviderUnreachable, "server": ProviderUnavailable}


class Hearing:
    def __init__(self) -> None:
        self.retries = 0

    def retried(self) -> None:
        self.retries += 1


@given(
    script=st.lists(st.sampled_from(["connect", "timeout", "server", "ok", "client"]), min_size=1, max_size=6),
)
@settings(max_examples=60, deadline=None)
def test_only_what_may_pass_is_retried_three_times_with_growing_waits_and_the_last_failure_names_the_error(
    script: list[str],
) -> None:
    answers = {
        "ok": lambda: httpx.Response(200, json=ONE_CELL),
        "client": lambda: httpx.Response(400, json={"error_code": 150, "error": "too big"}),
        **FAILURES,
    }
    engine = ScriptedEngine(sources_to_targets=[answers[kind]() for kind in script])
    waits: list[float] = []
    hearing = Hearing()

    # the written rule: a call that may pass is made again, up to three times; "ok" and 4xx end the story at once
    ended = next((i for i, kind in enumerate(script) if kind in ("ok", "client") or i == 3), len(script) - 1)
    last = script[ended]
    if ended == len(script) - 1 and last not in ("ok", "client"):
        ended, last = 3, script[-1]  # the engine repeats its last answer
    expected_calls = ended + 1
    outcome: object
    try:
        outcome = provider(httpx.MockTransport(engine), waits=waits).matrix([TORINO], [SUSA], hearing)
    except (ProviderUnreachable, ProviderUnavailable, ProviderRejected) as failure:
        outcome = type(failure)

    expected_outcome = (
        [[RoadMeasure(56099, 3342)]] if last == "ok" else ProviderRejected if last == "client" else RAISED[last]
    )
    assert (outcome, len(engine.asked("sources_to_targets")), waits, hearing.retries) == (
        expected_outcome,
        expected_calls,
        [base + JITTER_S for base in RETRY_WAITS[: expected_calls - 1]],
        expected_calls - 1,
    )


def test_a_matrix_answer_after_one_server_error_is_the_recorded_one_and_the_observer_hears_one_retry() -> None:
    recorded = recording("matrix_confirmed_with_island_null_row")
    request = recorded["request"]
    engine = ScriptedEngine(
        sources_to_targets=[httpx.Response(503, text="busy"), httpx.Response(200, json=recorded["response"])]
    )
    hearing = Hearing()

    answer = provider(httpx.MockTransport(engine)).matrix(
        places(request["sources"]), places(request["targets"]), hearing
    )

    assert ([list(row) for row in answer], hearing.retries) == (
        [[RoadMeasure(68613, 4058), RoadMeasure(112134, 6140)], [None, None]],
        1,
    )


def test_a_probe_waits_for_no_retry_and_tells_no_observer() -> None:
    engine = ScriptedEngine(sources_to_targets=[httpx.Response(503, text="busy")])
    waits: list[float] = []

    result = provider(httpx.MockTransport(engine), waits=waits).probe()

    assert (result, len(engine.asked("sources_to_targets")), waits) == (
        ProbeResult("degraded-healthy", "routing_engine_not_ready"),
        1,
        [],
    )


def _torino_susa_grid(cells: list[tuple[float | None, int | None]]) -> dict[str, Any]:
    rows = [cells[:2], cells[2:]]
    return {
        "sources_to_targets": [
            [{"from_index": i, "to_index": j, "distance": d, "time": t} for j, (d, t) in enumerate(row)]
            for i, row in enumerate(rows)
        ]
    }


GOOD_GRID = _torino_susa_grid([(0.0, 0), (80.1, 4200), (80.2, 4300), (0.0, 0)])
NULL_CELL = _torino_susa_grid([(0.0, 0), (None, None), (80.2, 4300), (0.0, 0)])
ZERO_CELL = _torino_susa_grid([(0.0, 0), (80.1, 4200), (0.0, 0), (0.0, 0)])


@pytest.mark.parametrize(
    ("status", "matrix", "expected"),
    [
        (
            httpx.Response(200, json={"version": "3.9.1", "tileset_last_modified": 5}),
            httpx.Response(200, json=GOOD_GRID),
            ProbeResult("ok"),
        ),
        (httpx.ConnectError("refused"), None, ProbeResult("degraded-healthy", "routing_engine_unreachable")),
        (
            httpx.Response(200, json={"version": "3.9.1", "tileset_last_modified": 5}),
            httpx.ReadTimeout("slow"),
            ProbeResult("degraded-healthy", "routing_engine_unreachable"),
        ),
        (httpx.Response(502, text="bad gateway"), None, ProbeResult("degraded-healthy", "routing_engine_not_ready")),
        (
            httpx.Response(200, text="<html>loading</html>"),
            None,
            ProbeResult("degraded-healthy", "routing_engine_not_ready"),
        ),
        (
            httpx.Response(200, json={"version": "3.9.1", "tileset_last_modified": 5}),
            httpx.Response(200, json=NULL_CELL),
            ProbeResult("degraded-healthy", "routing_engine_not_ready"),
        ),
        (
            httpx.Response(200, json={"version": "3.9.1", "tileset_last_modified": 5}),
            httpx.Response(200, json=ZERO_CELL),
            ProbeResult("degraded-healthy", "routing_engine_not_ready"),
        ),
        (
            httpx.Response(200, json={"version": "3.9.1", "tileset_last_modified": 5}),
            httpx.Response(400, json={"error_code": 170, "error": "x"}),
            ProbeResult("degraded-healthy", "routing_engine_not_ready"),
        ),
        (
            httpx.Response(200, json={"version": "3.10.0", "tileset_last_modified": 5}),
            None,
            ProbeResult("degraded-healthy", "routing_engine_version_mismatch: found 3.10.0, expected 3.9.1"),
        ),
    ],
    ids=[
        "ok",
        "connect-refused",
        "matrix-timeout",
        "status-5xx",
        "status-unreadable",
        "null-cell",
        "zero-cell",
        "matrix-4xx",
        "other-version",
    ],
)
def test_a_probe_reads_status_then_the_torino_susa_matrix_and_is_never_fatal(
    status: httpx.Response | Exception, matrix: httpx.Response | Exception | None, expected: ProbeResult
) -> None:
    scripts: dict[str, list[httpx.Response | Exception]] = {"status": [status]}
    if matrix is not None:
        scripts["sources_to_targets"] = [matrix]
    engine = ScriptedEngine(**scripts)

    result = provider(httpx.MockTransport(engine)).probe()

    assert result == expected
    if matrix is not None:
        asked = engine.asked("sources_to_targets")[0]
        assert [(p["lat"], p["lon"]) for p in asked["sources"]] == [(45.0703, 7.6869), (45.1370, 7.0500)]
        assert asked["targets"] == asked["sources"]


def test_a_probe_that_reads_a_status_updates_the_identity_even_when_the_version_is_another() -> None:
    engine = ScriptedEngine(status=[httpx.Response(200, json={"version": "3.10.0", "tileset_last_modified": 5})])
    adapter = provider(httpx.MockTransport(engine))

    adapter.probe()

    with pytest.raises(ProviderUnavailable, match=r"3\.10\.0"):
        _ = adapter.provider_id


# the 170 flow ----------------------------------------------------------------------------------------------------

FAR = Coordinate(45.37355, 6.96584)
NEAR_A, NEAR_B, NEAR_C = Coordinate(44.9, 6.6), Coordinate(44.3, 7.3), Coordinate(44.5, 7.0)
REFUSAL_170 = httpx.Response(400, json={"error_code": 170, "error": "Locations are in unconnected regions."})


def located(*unsnappable: Coordinate) -> Any:
    def answer(request: httpx.Request) -> httpx.Response:
        asked = json.loads(request.content)["locations"]
        return httpx.Response(
            200,
            json=[
                {
                    "input_lat": p["lat"],
                    "input_lon": p["lon"],
                    "edges": [] if Coordinate(p["lat"], p["lon"]) in unsnappable else [{"way_id": 1}],
                    "nodes": [],
                }
                for p in asked
            ],
        )

    return answer


class Engine170:
    """A scripted engine: /sources_to_targets refuses with 170 while a place of `unsnappable` is asked; /locate says
    which of the asked places have no edge; the other cells are answered `1000 * (target number)` m and seconds."""

    def __init__(self, unsnappable: set[Coordinate], *, locate_finds: set[Coordinate] | None = None) -> None:
        self.unsnappable = unsnappable
        self.locate_finds = unsnappable if locate_finds is None else locate_finds
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        if request.url.path == "/locate":
            return located(*self.locate_finds)(request)
        asked = {Coordinate(p["lat"], p["lon"]) for p in body["sources"] + body["targets"]}
        if asked & self.unsnappable:
            return REFUSAL_170
        rows = [
            [
                {"from_index": i, "to_index": j, "time": 100 * (j + 1), "distance": float(j + 1)}
                for j, _ in enumerate(body["targets"])
            ]
            for i, _ in enumerate(body["sources"])
        ]
        return httpx.Response(200, json={"sources_to_targets": rows})

    def questions(self) -> list[dict[str, Any]]:
        return [body for path, body in self.calls if path == "/sources_to_targets"]


@given(
    sources=st.lists(st.sampled_from([FAR, NEAR_A, NEAR_B, NEAR_C, TORINO]), min_size=1, max_size=3, unique=True),
    targets=st.lists(st.sampled_from([FAR, NEAR_A, NEAR_B, NEAR_C, SUSA]), min_size=1, max_size=3, unique=True),
)
@settings(max_examples=60, deadline=None)
def test_a_place_the_engine_cannot_snap_answers_its_cells_off_network_and_never_removes_the_others(
    sources: list[Coordinate], targets: list[Coordinate]
) -> None:
    engine = Engine170({FAR})
    answer = provider(httpx.MockTransport(engine)).matrix(sources, targets)

    kept_targets = [t for t in targets if t != FAR]
    expected = [
        [
            OffNetwork(frozenset(p for p in (source, target) if p == FAR))
            if FAR in (source, target)
            else RoadMeasure(1000 * (kept_targets.index(target) + 1), 100 * (kept_targets.index(target) + 1))
            for target in targets
        ]
        for source in sources
    ]
    assert [list(row) for row in answer] == expected
    asked_again = engine.questions()[1:]
    kept_sources = [p for p in sources if p != FAR]
    asked_once_more = FAR in (*sources, *targets) and bool(kept_sources) and bool(kept_targets)
    assert (len(asked_again) == int(asked_once_more)) and all(
        Coordinate(p["lat"], p["lon"]) != FAR for q in asked_again for p in q["sources"] + q["targets"]
    )


def test_both_ends_off_network_are_named_and_a_second_matrix_call_asks_the_engine_again() -> None:
    engine = Engine170({FAR, NEAR_A})
    adapter = provider(httpx.MockTransport(engine))

    first = adapter.matrix([FAR], [NEAR_A])
    second = adapter.matrix([FAR], [NEAR_A])

    assert [list(row) for row in first] == [[OffNetwork(frozenset({FAR, NEAR_A}))]] == [list(row) for row in second]
    assert [path for path, _ in engine.calls] == ["/sources_to_targets", "/locate"] * 2


def test_the_places_are_located_verbosely_with_the_same_cutoff_and_costing() -> None:
    engine = Engine170({FAR})
    provider(httpx.MockTransport(engine)).matrix([TORINO], [FAR, SUSA])

    locate = next(body for path, body in engine.calls if path == "/locate")
    question = engine.questions()[0]
    assert (locate["verbose"], locate["costing"], locate["costing_options"], locate["locations"]) == (
        True,
        question["costing"],
        question["costing_options"],
        question["sources"] + question["targets"],
    )


def test_a_170_that_no_located_place_explains_is_a_rejection_naming_170_never_a_missing_road() -> None:
    engine = Engine170({FAR}, locate_finds=set())

    with pytest.raises(ProviderRejected, match="170"):
        provider(httpx.MockTransport(engine)).matrix([TORINO], [FAR, SUSA])


def test_a_170_that_comes_back_after_the_unsnappable_places_are_dropped_is_a_rejection() -> None:
    engine = Engine170({FAR, NEAR_A}, locate_finds={FAR})

    with pytest.raises(ProviderRejected, match="170"):
        provider(httpx.MockTransport(engine)).matrix([TORINO], [FAR, NEAR_A])

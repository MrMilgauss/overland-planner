"""Step definitions of the routing-port contract (slice 06a). The Then steps may assert how the planner questions the
engine (D186): that is the contract. The engine is scripted through respx, from the recorded Valhalla 3.9.1 answers."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import respx
from pytest_bdd import given, parsers, then, when

from overland_planner.adapters.routing.valhalla_routing_provider import ValhallaRoutingProvider
from overland_planner.application.ports.routing_provider import (
    ProviderUnavailable,
    ProviderUnreachable,
    RoadCell,
    RoutingProviderError,
)
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import OffNetwork, RoadMeasure
from tests.contract.routing_port.recordings import REPLAY_URL, BatchLimitedEngine, recording
from tests.contract.routing_port.test_engine_recordings import require_recorded_engine

SNAP_M = 250
TORINO_SUSA = [{"lat": 45.0703, "lon": 7.6869}, {"lat": 45.1370, "lon": 7.0500}]
TRIP_ITEMS = 60  # 60 items + Start and End: 61 places ask 60 destinations (D131), 3,660 pairs


@dataclass
class ContractWorld:
    answer: Sequence[Sequence[RoadCell]] = ()  # type: ignore[assignment]
    engine: BatchLimitedEngine | None = None
    sources: list[Coordinate] = field(default_factory=list)
    targets: list[Coordinate] = field(default_factory=list)
    recorded: dict[str, Any] = field(default_factory=dict)
    failure: RoutingProviderError | None = None
    stopped: str | None = None
    far_place: Coordinate | None = None


@pytest.fixture
def world() -> ContractWorld:
    return ContractWorld()


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=REPLAY_URL, assert_all_called=False) as mocked:
        mocked.get("/status").respond(json=recording("status")["response"])
        yield mocked


def _provider(max_matrix_pairs: int = 2500) -> ValhallaRoutingProvider:
    return ValhallaRoutingProvider(
        REPLAY_URL,
        expected_version="3.9.1",
        max_matrix_pairs=max_matrix_pairs,
        concurrency=2,
        snap_m=SNAP_M,
        sleep=lambda seconds: None,  # the contract never waits
        jitter=lambda: 0.0,
    )


def _place(location: dict[str, Any]) -> Coordinate:
    return Coordinate(location["lat"], location["lon"])


def _posted(router: respx.MockRouter) -> list[dict[str, Any]]:
    return [json.loads(call.request.content) for call in router.calls if call.request.url.path == "/sources_to_targets"]


# Scenario: A Torino to Susa connection is read as one Confirmed leg


@given("the routing engine answers with its recorded Torino to Susa route on the 4x4 profile")
def _engine_with_torino_susa_route(router: respx.MockRouter, world: ContractWorld) -> None:
    """The port has no route method yet (slice 09): the planner asks the leg through `matrix`, and the scripted engine
    answers that 1x1 matrix with a cell built from the recorded /route answer's distance (km) and time (s)."""
    route = recording("route_torino_susa_4x4v1")
    summary = route["response"]["trip"]["legs"][0]["summary"]
    cell = {"from_index": 0, "to_index": 0, "time": round(summary["time"]), "distance": summary["length"]}
    router.post("/sources_to_targets").respond(json={"sources_to_targets": [[cell]]})
    world.recorded = route["request"]


@when("the planner asks for the leg from Torino to Susa")
def _ask_torino_susa(world: ContractWorld) -> None:
    origin, destination = (_place(location) for location in world.recorded.get("locations", TORINO_SUSA))
    try:
        world.answer = _provider().matrix([origin], [destination])
    except RoutingProviderError as failure:
        world.failure = failure


@then("it gets one Confirmed leg with the recorded distance and duration")
def _one_confirmed_leg(router: respx.MockRouter, world: ContractWorld) -> None:
    # recorded: 56.099 km in 3341.837 s -> 56,099 m and 3,342 s
    assert world.answer == [[RoadMeasure(distance_m=56099, duration_s=3342)]]
    origin, destination = world.recorded["locations"]
    asked = {key: world.recorded[key] for key in ("costing", "costing_options")}
    assert _posted(router) == [{"sources": [origin], "targets": [destination], **asked}]


# Scenario: A missing matrix answer confirmed by a route check means no connection at that level


@given("the routing engine answers with its recorded matrix that has an empty row for an island")
def _engine_with_island_matrix(router: respx.MockRouter, world: ContractWorld) -> None:
    matrix = recording("matrix_confirmed_with_island_null_row")
    router.post("/sources_to_targets", json=matrix["request"]).respond(matrix["status"], json=matrix["response"])
    world.recorded = matrix


@given("its recorded route check for that island finds no path")
def _island_route_check_finds_no_path(world: ContractWorld) -> None:
    """Documentary: the adapter makes no /route call. This only checks the recording is the 442 it claims to be
    (allow_second_pass is why the matrix's null row is trusted), for the island asked from."""
    check = recording("route_442_island_source")
    assert check["response"]["error_code"] == 442
    island = world.recorded["request"]["sources"][1]
    assert check["request"]["locations"][0] == island


@when("the planner asks for the legs from the island")
def _ask_from_island(world: ContractWorld) -> None:
    request = world.recorded["request"]
    world.answer = _provider().matrix([_place(p) for p in request["sources"]], [_place(p) for p in request["targets"]])


@then("every leg from the island has no connection at the Confirmed level")
def _island_row_is_empty(world: ContractWorld) -> None:
    assert list(world.answer[1]) == [None, None]


@then("no leg of the other places is affected")
def _other_row_is_measured(world: ContractWorld) -> None:
    first_row = world.recorded["response"]["sources_to_targets"][0]
    assert list(world.answer[0]) == [
        RoadMeasure(distance_m=round(cell["distance"] * 1000), duration_s=cell["time"]) for cell in first_row
    ]


# Scenario: A large trip is asked in batches the routing engine accepts


@given("the routing engine accepts at most 2,500 legs per question, as in its recorded refusal")
def _engine_with_pair_limit(router: respx.MockRouter, world: ContractWorld) -> None:
    refusal = recording("matrix_150_pair_limit")["response"]["error"]  # "Exceeded max locations: 2500.000000"
    limit = int(float(refusal.rsplit(": ", 1)[1]))
    assert limit == 2500
    world.sources = [Coordinate(44.0 + i / 100, 7.0) for i in range(TRIP_ITEMS + 1)]
    world.targets = [Coordinate(44.0, 7.5 + j / 100) for j in range(TRIP_ITEMS)]
    world.engine = BatchLimitedEngine(limit, world.sources, world.targets)
    router.post("/sources_to_targets").mock(side_effect=world.engine)


@when("the planner asks for the 3,660 legs of the 60-item one-way trip")
def _ask_whole_trip(world: ContractWorld) -> None:
    world.answer = _provider().matrix(world.sources, world.targets)


@then("every leg is answered")
def _every_leg_is_answered(world: ContractWorld) -> None:
    expected = [
        [RoadMeasure(*BatchLimitedEngine.measure(i, j)) for j in range(len(world.targets))]
        for i in range(len(world.sources))
    ]
    assert [list(row) for row in world.answer] == expected


@then("no single question to the routing engine held more than 2,500 legs")
def _no_question_above_the_limit(world: ContractWorld) -> None:
    assert world.engine is not None
    assert world.engine.refusals == 0
    assert sum(world.engine.question_sizes) == 3660 and max(world.engine.question_sizes) <= 2500


# Scenario: One place the routing engine cannot snap never removes the other places' legs


@given("the routing engine answers with its recorded refusal for a batch that contains one place far from any road")
def _engine_refuses_batch_with_a_far_place(router: respx.MockRouter, world: ContractWorld) -> None:
    refusal = recording("matrix_170_unsnappable_location_kills_call")
    located = recording("locate_far_point_empty_edges_cutoff250")["response"]
    world.recorded = refusal
    far = located[0]  # recorded with `edges: []`
    world.far_place = Coordinate(far["input_lat"], far["input_lon"])

    def sources_to_targets(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if any(place["lat"] == far["input_lat"] for place in body["sources"] + body["targets"]):
            return httpx.Response(refusal["status"], json=refusal["response"])
        rows = [
            [
                {"from_index": a, "to_index": b, "time": 100 * (b + 1), "distance": float(b + 1)}
                for b, _ in enumerate(body["targets"])
            ]
            for a, _ in enumerate(body["sources"])
        ]
        return httpx.Response(200, json={"sources_to_targets": rows})

    def locate(request: httpx.Request) -> httpx.Response:
        recorded_points = {(entry["input_lat"], entry["input_lon"]): entry for entry in located}
        snapped = {"edges": [{"way_id": 1, "percent_along": 0.5}], "nodes": []}
        asked = json.loads(request.content)["locations"]
        return httpx.Response(
            200,
            json=[
                recorded_points.get((p["lat"], p["lon"]), {"input_lat": p["lat"], "input_lon": p["lon"], **snapped})
                for p in asked
            ],
        )

    router.post("/sources_to_targets").mock(side_effect=sources_to_targets)
    router.post("/locate").mock(side_effect=locate)


@when("the planner asks for that batch of legs")
def _ask_the_batch(world: ContractWorld) -> None:
    request = world.recorded["request"]
    world.sources = [_place(p) for p in request["sources"]]
    world.targets = [_place(p) for p in request["targets"]]
    world.answer = _provider().matrix(world.sources, world.targets)


@then("the other places' legs are answered")
def _other_legs_answered(world: ContractWorld) -> None:
    assert list(world.answer[0]) == [
        RoadMeasure(distance_m=1000, duration_s=100),
        RoadMeasure(distance_m=2000, duration_s=200),
    ]


@then("the far place is not recorded as having no connection")
def _far_place_is_off_network(world: ContractWorld) -> None:
    far = world.far_place
    assert far is not None
    assert list(world.answer[1]) == [OffNetwork(frozenset({far})), OffNetwork(frozenset({far}))]
    assert all(cell is not None for row in world.answer for cell in row)


@then("the planner asked again without that place")
def _asked_again_without_the_far_place(router: respx.MockRouter, world: ContractWorld) -> None:
    first, second = _posted(router)
    assert first == world.recorded["request"]
    assert second["sources"] == first["sources"][:1] and second["targets"] == first["targets"]


# Scenario: The contract checks stop when the engine is not the version they were recorded against


@given(parsers.parse('the routing engine reports version "{found}" instead of the recorded "{recorded}"'))
def _engine_of_another_version(router: respx.MockRouter, found: str, recorded: str) -> None:
    router.get("/status").respond(json={"version": found, "tileset_last_modified": 1})


@when("the routing-engine contract checks run against it")
def _run_the_contract_checks(world: ContractWorld) -> None:
    with httpx.Client(base_url=REPLAY_URL) as client:
        try:
            require_recorded_engine(client)
        except pytest.exit.Exception as stopped:
            world.stopped = stopped.msg


@then(parsers.parse('they stop with "{line}"'))
def _the_checks_stop(world: ContractWorld, line: str) -> None:
    assert world.stopped == line


# Scenario Outline: Routing engine failures are reported as failures, never as missing roads


@given(
    parsers.re(
        r"the routing engine (?P<failure>refuses connections|does not answer within the time limit"
        r"|keeps answering with a server error)"
    )
)
def _engine_fails(router: respx.MockRouter, failure: str) -> None:
    route = router.post("/sources_to_targets")
    if failure == "refuses connections":
        route.mock(side_effect=httpx.ConnectError("connection refused"))
    elif failure == "does not answer within the time limit":
        route.mock(side_effect=httpx.ReadTimeout("no answer"))
    else:
        route.respond(503, text="busy")


@then(parsers.re(r"the planner reports the routing engine as (?P<reported>unreachable|unavailable)"))
def _failure_is_reported(world: ContractWorld, reported: str) -> None:
    expected = {"unreachable": ProviderUnreachable, "unavailable": ProviderUnavailable}[reported]
    assert type(world.failure) is expected


@then("no leg is recorded as having no connection")
def _no_leg_recorded(world: ContractWorld) -> None:
    assert list(world.answer) == []

"""Step definitions of the routing-port contract (slice 06a). The Then steps may assert how the planner questions the
engine (D186): that is the contract. The engine is scripted through respx, from the recorded Valhalla 3.9.1 answers.

The offline road map (MockRoutingProvider) runs the same checks, scripted with the same connections and failures
(parity scenario). Not applicable to it, because it has neither: the 2,500-leg batch limit (it answers any batch at
once) and the engine version check (it has no version)."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import yaml
from pytest_bdd import given, parsers, then, when

from overland_planner.adapters.routing.mock_routing_provider import MockRoutingProvider, read_road_map
from overland_planner.adapters.routing.valhalla_routing_provider import ValhallaRoutingProvider
from overland_planner.application.planning.facade import PlanJobRegistry, PlanRequestJob
from overland_planner.application.platform.diagnostics_service import DiagnosticsService
from overland_planner.application.ports.diagnostics_reader import JobLogRow
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.routing_provider import (
    ProviderUnavailable,
    ProviderUnreachable,
    RoadCell,
    RoutingProviderError,
)
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.routing.road_leg import OffNetwork, RoadMeasure
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.contract.routing_port.recordings import REPLAY_URL, BatchLimitedEngine, recording
from tests.contract.routing_port.test_engine_recordings import (
    TOLERANCE,
    require_expected_tileset,
    require_recorded_engine,
)
from tests.unit.application.planning.planning_doubles import InMemoryPlanJobLog, InMemoryPlanning, job_when_ended
from tests.unit.application.planning.scripted_tour_solver import ScriptedTourSolver
from tests.unit.domain.planning.trips import PROJECT

SNAP_M = 250
TORINO_SUSA = [{"lat": 45.0703, "lon": 7.6869}, {"lat": 45.1370, "lon": 7.0500}]
TRIP_ITEMS = 60  # 60 items + Start and End: 61 places ask 60 destinations (D131), 3,660 pairs


class _Observer:
    """Counts the retries the road map made, as the plan job's look-up hears them."""

    def __init__(self) -> None:
        self.retries = 0

    def retried(self) -> None:
        self.retries += 1


class _Hiccup:
    """A scripted engine that answers one server error, then the recorded 1x1 cell for every cell asked."""

    def __init__(self, cell: dict[str, Any]) -> None:
        self._cell = cell
        self.calls = 0

    def rearm(self) -> None:
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls == 1:
            return httpx.Response(503, text="busy")
        body = json.loads(request.content)
        rows = [[self._cell for _ in body["targets"]] for _ in body["sources"]]
        return httpx.Response(200, json={"sources_to_targets": rows})


@dataclass(frozen=True)
class LiveEngine:
    """The engine at `--valhalla-url` (make contract-live); `exact` when it serves the recorded map data."""

    url: str
    exact: bool


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
    observer: _Observer = field(default_factory=_Observer)
    hiccup: _Hiccup | None = None
    offline: dict[str, Any] = field(default_factory=dict)
    live: LiveEngine | None = None
    live_differences: list[str] = field(default_factory=list)


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
        world.answer = _provider().matrix([origin], [destination], world.observer)
    except RoutingProviderError as failure:
        world.failure = failure


@then("it gets one Confirmed leg with the recorded distance and duration")
def _one_confirmed_leg(router: respx.MockRouter, world: ContractWorld) -> None:
    # recorded: 56.099 km in 3341.837 s -> 56,099 m and 3,342 s
    assert world.answer == [[RoadMeasure(distance_m=56099, duration_s=3342)]]
    origin, destination = world.recorded["locations"]
    asked = {key: world.recorded[key] for key in ("costing", "costing_options")}
    asked_once = {"sources": [origin], "targets": [destination], **asked}
    assert _posted(router) == [asked_once] * (1 + world.observer.retries)  # a retry asks the same question again


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
    if world.live is not None:
        world.live_differences = _checks_of_the_live_engine(world.live)
        return
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


# Scenario: A passing server hiccup is retried and the plan still counts toward the 3-minute promise


@given("the routing engine answers with a server error once and then with its recorded Torino to Susa route")
def _engine_with_a_hiccup(router: respx.MockRouter, world: ContractWorld) -> None:
    route = recording("route_torino_susa_4x4v1")
    summary = route["response"]["trip"]["legs"][0]["summary"]
    cell = {"from_index": 0, "to_index": 0, "time": round(summary["time"]), "distance": summary["length"]}
    world.hiccup = _Hiccup(cell)
    router.post("/sources_to_targets").mock(side_effect=world.hiccup)
    world.recorded = route["request"]


@then("the plan is marked as retried, and still counts toward the 3-minute promise")
def _the_plan_is_marked_as_retried(world: ContractWorld) -> None:
    """A plan job whose look-up asks Torino and Susa of this engine hears the hiccup: the poll and the job's log row say
    `retried`, and the job is a done one, with its elapsed time, which every K5 count reads."""
    assert world.hiccup is not None and world.observer.retries == 1
    world.hiccup.rearm()
    torino, susa = (_place(location) for location in world.recorded["locations"])
    home = PoiItem(id="start", project_id=PROJECT, name="Torino", location=torino)
    stop = PoiItem(id="susa", project_id=PROJECT, name="Susa", location=susa)
    planning = InMemoryPlanning()
    planning.add_project(PROJECT, ProjectSnapshot(home.id, home.id, (home, stop)))
    clock, log = FakeClock(), RecordingEventLog()
    job = PlanRequestJob(
        planning.unit_of_work, LegResolver(_provider()), ScriptedTourSolver(None), 500, clock, log, InMemoryFileStore()
    )
    job_log = InMemoryPlanJobLog(planning)
    registry = PlanJobRegistry(clock, job, log, job_log=job_log)
    job_id = registry.start(PROJECT)
    assert job_id is not None
    ended = job_when_ended(registry, job_id)
    (entry,) = job_log.rows
    row = entry.columns()
    assert (ended.state, ended.retried, ended.legs_new) == ("done", True, 2)
    assert (row["terminal_state"], row["retried"]) == ("done", True)
    report = _diagnostics_over(
        JobLogRow(
            project_id=PROJECT,
            project_name="Torino to Susa",
            started_at=entry.started_at,
            terminal_state=str(row["terminal_state"]),
            elapsed_ms=int(str(row["elapsed_ms"])),
            memo_hit=bool(row["memo_hit"]),
            items_included=int(str(row["items_included"])),
            retried=bool(row["retried"]),
        ),
        clock,
    )
    band = "le_30"  # two items included
    assert report.k5.retried_jobs[band] == 1, "the retried job is counted apart"
    assert report.k5.e2e_p95_by_band_s[band] is not None, "the retried job is left out of the 3-minute figure"
    assert report.jobs_by_terminal_state == {"done": 1}


def _diagnostics_over(job: JobLogRow, clock: FakeClock) -> Any:
    """The K5 population the diagnostics count from one job row: the real `DiagnosticsService` over a reader of it."""

    class _OneJob:
        def project_exists(self, project_id: str) -> bool:
            return True

        def jobs_since(self, since: Any) -> list[JobLogRow]:
            return [job]

        def plan_runs(self) -> list[Any]:
            return []

        def refusals_since(self, since: Any) -> list[Any]:
            return []

        def probe(self) -> Any:
            return ProbeResult(outcome="ok")

    return DiagnosticsService(_OneJob(), clock, version="test", process_started_at=clock.now()).report()


# Scenario: The offline road map reports connections and failures the same way as the routing engine

_FAILURES = {
    "refuses connections": ("unreachable", httpx.ConnectError("connection refused")),
    "does not answer within the time limit": ("unreachable", httpx.ReadTimeout("no answer")),
    "keeps answering with a server error": ("unavailable", httpx.Response(503, text="busy")),
}


def _outcome(ask: Callable[[_Observer], Sequence[Sequence[RoadCell]]]) -> tuple[Any, ...]:
    """What a check gives: the cells answered and the retries heard, or the typed failure."""
    observer = _Observer()
    try:
        answer = ask(observer)
    except RoutingProviderError as failure:
        return ("failed", type(failure).__name__)
    return ("answered", tuple(tuple(row) for row in answer), observer.retries)


@contextmanager
def _recorded_engine() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=REPLAY_URL, assert_all_called=False) as mocked:
        mocked.get("/status").respond(json=recording("status")["response"])
        yield mocked


def _places(entries: Sequence[dict[str, Any]]) -> list[Coordinate]:
    return [_place(entry) for entry in entries]


def _measured(cell: dict[str, Any]) -> RoadMeasure | None:
    return (
        None
        if cell["time"] is None
        else RoadMeasure(distance_m=round(cell["distance"] * 1000), duration_s=cell["time"])
    )


def _far_place_engine(router: respx.MockRouter, world: ContractWorld) -> None:
    _engine_refuses_batch_with_a_far_place(router, world)


def _checks_of_the_recorded_engine(world: ContractWorld) -> dict[str, tuple[Any, ...]]:
    """The recorded engine's outcome of each check, each against its own scripted engine."""
    outcomes: dict[str, tuple[Any, ...]] = {}
    torino, susa = _places(TORINO_SUSA)
    with _recorded_engine() as router:
        _engine_with_torino_susa_route(router, world)
        outcomes["Torino to Susa"] = _outcome(lambda _: _provider().matrix([torino], [susa]))
    island = recording("matrix_confirmed_with_island_null_row")
    with _recorded_engine() as router:
        router.post("/sources_to_targets", json=island["request"]).respond(island["status"], json=island["response"])
        sources, targets = _places(island["request"]["sources"]), _places(island["request"]["targets"])
        outcomes["the island"] = _outcome(lambda _: _provider().matrix(sources, targets))
    far = recording("matrix_170_unsnappable_location_kills_call")
    with _recorded_engine() as router:
        _far_place_engine(router, world)
        sources, targets = _places(far["request"]["sources"]), _places(far["request"]["targets"])
        outcomes["the far place"] = _outcome(lambda _: _provider().matrix(sources, targets))
    for failure, (_, step) in _FAILURES.items():
        with _recorded_engine() as router:
            route = router.post("/sources_to_targets")
            if isinstance(step, Exception):
                route.mock(side_effect=step)
            else:
                route.mock(return_value=step)
            outcomes[failure] = _outcome(lambda _: _provider().matrix([torino], [susa]))
    with _recorded_engine() as router:
        _engine_with_a_hiccup(router, world)
        outcomes["a server hiccup"] = _outcome(lambda observer: _provider().matrix([torino], [susa], observer))
    return outcomes


def _scripted_road_maps(tmp_path: Path) -> dict[str, Path]:
    """The recorded answers as offline road maps: `connections` (Torino to Susa, the island with no connection) and
    `far place` (the other places' legs, the far place off the network). The far-place engine's answers repeat a pair
    the island's recording answers differently, so each has its own script."""
    torino, susa = TORINO_SUSA
    connections: list[dict[str, Any]] = [
        {
            "from": [torino["lat"], torino["lon"]],
            "to": [susa["lat"], susa["lon"]],
            "distance_m": 56099,
            "duration_s": 3342,
        }
    ]
    island = recording("matrix_confirmed_with_island_null_row")
    sources, targets = island["request"]["sources"], island["request"]["targets"]
    for a, row in enumerate(island["response"]["sources_to_targets"]):
        for b, cell in enumerate(row):
            measure = _measured(cell)
            entry: dict[str, Any] = {
                "from": [sources[a]["lat"], sources[a]["lon"]],
                "to": [targets[b]["lat"], targets[b]["lon"]],
            }
            figures = (
                {"level": "none"}
                if measure is None
                else {"distance_m": measure.distance_m, "duration_s": measure.duration_s}
            )
            connections.append(entry | figures)
    far = recording("matrix_170_unsnappable_location_kills_call")["request"]
    first, far_place = far["sources"]
    others: list[dict[str, Any]] = [  # what the far-place engine answers for the first source
        {
            "from": [first["lat"], first["lon"]],
            "to": [t["lat"], t["lon"]],
            "distance_m": 1000 * (b + 1),
            "duration_s": 100 * (b + 1),
        }
        for b, t in enumerate(far["targets"])
    ]
    documents = {
        "connections": {"pairs": connections},
        "far place": {"pairs": others, "off_network": [[far_place["lat"], far_place["lon"]]]},
    }
    paths = {name: tmp_path / f"{name.replace(' ', '-')}-road-map.yaml" for name in documents}
    for name, document in documents.items():
        paths[name].write_text(yaml.safe_dump(document), encoding="utf-8")
    return paths


def _checks_of_the_offline_road_map(paths: dict[str, Path]) -> dict[str, tuple[Any, ...]]:
    path = paths["connections"]

    def armed(faults: dict[str, object] | None) -> MockRoutingProvider:
        provider = MockRoutingProvider(script=read_road_map(path))
        if faults is not None:
            document = {"pairs": [], "faults": faults}
            faults_path = path.with_name("faults.yaml")
            faults_path.write_text(yaml.safe_dump(document), encoding="utf-8")
            provider.arm_faults(read_road_map(faults_path).faults)
        return provider

    torino, susa = _places(TORINO_SUSA)
    island = recording("matrix_confirmed_with_island_null_row")["request"]
    far = recording("matrix_170_unsnappable_location_kills_call")["request"]
    outcomes = {
        "Torino to Susa": _outcome(lambda _: armed(None).matrix([torino], [susa])),
        "the island": _outcome(lambda _: armed(None).matrix(_places(island["sources"]), _places(island["targets"]))),
        "the far place": _outcome(
            lambda _: MockRoutingProvider(script=read_road_map(paths["far place"])).matrix(
                _places(far["sources"]), _places(far["targets"])
            )
        ),
    }
    for failure, (kind, _) in _FAILURES.items():
        outcomes[failure] = _outcome(
            lambda _, kind=kind: armed({"fail_after_pairs": 0, "kind": kind}).matrix([torino], [susa])
        )
    outcomes["a server hiccup"] = _outcome(
        lambda observer: armed({"fail_once_on_call": 1, "kind": "unavailable"}).matrix([torino], [susa], observer)
    )
    return outcomes


@given("the offline road map scripted with the same connections and failures as the recorded answers")
def _offline_road_map_scripted_like_the_recordings(world: ContractWorld, tmp_path: Path) -> None:
    world.recorded = {"road_maps": _scripted_road_maps(tmp_path)}


@when("the routing-engine contract checks run against the offline road map")
def _run_the_checks_against_the_offline_road_map(world: ContractWorld) -> None:
    world.offline = _checks_of_the_offline_road_map(world.recorded["road_maps"])


@then("every check gives the same result as for the recorded routing engine")
def _every_check_gives_the_same_result(world: ContractWorld) -> None:
    recorded = _checks_of_the_recorded_engine(world)
    assert recorded["Torino to Susa"] == ("answered", ((RoadMeasure(56099, 3342),),), 0)
    assert recorded["a server hiccup"] == ("answered", ((RoadMeasure(56099, 3342),),), 1)
    assert [recorded[name][1] for name in ("refuses connections", "keeps answering with a server error")] == [
        "ProviderUnreachable",
        "ProviderUnavailable",
    ]
    assert world.offline == recorded


# Scenario: The routing engine on the Pi still answers like its recordings (layer 2 of make contract-live, D235)


@given("the planner can reach Valhalla on Marco's Pi through the maintenance tunnel")
def _the_live_engine(request: pytest.FixtureRequest, world: ContractWorld) -> None:
    url = request.config.getoption("--valhalla-url")
    if not url:
        pytest.skip("live checks need --valhalla-url; without it the recordings are replayed")
    with httpx.Client(base_url=url, timeout=120) as client:
        status = require_recorded_engine(client)
    require_expected_tileset(status, request.config.getoption("--expect-tileset-modified"))
    world.live = LiveEngine(url, exact=status["tileset_last_modified"] == recording("status")["tileset_last_modified"])


def _live_provider(url: str) -> ValhallaRoutingProvider:
    return ValhallaRoutingProvider(
        url, expected_version="3.9.1", max_matrix_pairs=2500, concurrency=2, snap_m=SNAP_M, sleep=time.sleep
    )


def _near(recorded: int, live: int, *, exact: bool) -> bool:
    return recorded == live if exact else math.isclose(recorded, live, rel_tol=TOLERANCE)


def _measure_differences(name: str, recorded: RoadMeasure, live: object, *, exact: bool) -> list[str]:
    if not isinstance(live, RoadMeasure):
        return [f"{name}: {live!r} instead of {recorded}"]
    if _near(recorded.distance_m, live.distance_m, exact=exact) and _near(
        recorded.duration_s, live.duration_s, exact=exact
    ):
        return []
    return [f"{name}: {live} instead of {recorded}"]


def _checks_of_the_live_engine(engine: LiveEngine) -> list[str]:
    """The checks of the recorded engine that need no scripted fault, through the adapter at the live engine. What each
    does not cover: the failures and the hiccup need a scripted engine, and the 2,500-leg batching a counting one (the
    recorded refusal itself is checked raw by layer 1)."""
    provider, differences = _live_provider(engine.url), []
    torino, susa = _places(TORINO_SUSA)
    (answered,) = provider.matrix([torino], [susa])
    # The recorded Torino to Susa answer is a `/route` (56.099 km, 3341.837 s); the planner asks the matrix, whose
    # answer for the same path differs by rounding (live, 2026-11-17: 56,100 m and 3,341 s). SPIKE-2R measured matrix
    # and route distances within 0.01 %, so the check allows 0.1 % on the recorded tileset and 5 % after a refresh.
    differences += _route_differences("Torino to Susa", RoadMeasure(56099, 3342), answered[0], exact=engine.exact)
    island = recording("matrix_confirmed_with_island_null_row")
    sources, targets = _places(island["request"]["sources"]), _places(island["request"]["targets"])
    island_answer = provider.matrix(sources, targets)
    if list(island_answer[1]) != [None] * len(targets):
        differences.append(f"the island: {list(island_answer[1])!r} instead of no connection at any level")
    for cell, recorded in zip(island_answer[0], island["response"]["sources_to_targets"][0], strict=True):
        measure = RoadMeasure(distance_m=round(recorded["distance"] * 1000), duration_s=recorded["time"])
        differences += _measure_differences("the other places", measure, cell, exact=engine.exact)
    far = recording("matrix_170_unsnappable_location_kills_call")["request"]
    sources, targets = _places(far["sources"]), _places(far["targets"])
    far_answer = provider.matrix(sources, targets)
    if list(far_answer[1]) != [OffNetwork(frozenset({sources[1]}))] * len(targets):
        differences.append(f"the far place: {list(far_answer[1])!r} instead of off the network")
    differences += [
        f"the other places: {cell!r} is no leg" for cell in far_answer[0] if not isinstance(cell, RoadMeasure)
    ]
    return differences


def _route_differences(where: str, recorded: RoadMeasure, live: object, *, exact: bool) -> list[str]:
    """A matrix answer against a recorded `/route`: Confirmed, and distance and time within 0.1 % (5 % when the live
    map data is not the recorded one)."""
    tolerance = 0.001 if exact else 0.05
    if not isinstance(live, RoadMeasure) or live.level != "confirmed":
        return [f"{where}: {live!r} instead of a Confirmed leg"]
    close = all(
        abs(found - wanted) <= tolerance * wanted
        for found, wanted in ((live.distance_m, recorded.distance_m), (live.duration_s, recorded.duration_s))
    )
    return [] if close else [f"{where}: {live!r} is not within {tolerance:.1%} of {recorded!r}"]


@then("every check passes on the live routing engine")
def _every_live_check_passes(world: ContractWorld) -> None:
    assert not world.live_differences, "the live engine departs from its recordings: " + "; ".join(
        world.live_differences
    )

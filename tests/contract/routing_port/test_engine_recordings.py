"""Layer 1 of `make contract-live` (D235): the recorded Valhalla 3.9.1 answers against the engine, raw questions only.

Every check posts a recorded request and compares the answer with the recording. With `--valhalla-url` (and
`--run-external`) the engine is the live one; without it the same checks replay the recordings through respx, so the
comparison itself runs and blocks in CI. Layer 2, the routing-port suite through the planner's adapter, is slice 06a.

Compared exactly: HTTP status, error code and message, key sets, list lengths, null cells, integers and strings (the
route polyline too). Time, distance and length are exact when the live tileset is the recorded one (same
`tileset_last_modified`), else within 5 %. Floats that are not a measure (cost, heading, snapped coordinates) must be
numbers and nothing more.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "tests" / "contract" / "fixtures" / "valhalla-3.9.1"
REPLAY_URL = "http://valhalla.replay"
MEASURES = frozenset({"time", "distance", "length"})
TOLERANCE = 0.05
RECORDED_QUESTIONS = (
    "route_torino_susa_4x4v1",  # the Torino to Susa route
    "matrix_confirmed_5x5",  # the Confirmed 5x5 matrix
    "matrix_confirmed_with_island_null_row",  # the island null row ...
    "route_442_island_source",  # ... and its /route 442
    "matrix_150_pair_limit",  # 2,501 pairs: error 150
    "matrix_170_unsnappable_location_kills_call",  # a batch with a far place: error 170
    "route_171_near_point_cutoff250",  # error 171 on /route
    "locate_far_point_empty_edges_cutoff250",  # /locate answers 200 with empty edges
)


def recording(name: str) -> dict[str, Any]:
    recorded: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return recorded


def differences(recorded: Any, live: Any, *, exact: bool, path: str = "$") -> list[str]:
    """Where `live` departs from `recorded`; empty when the answers agree under the rules of the module docstring."""
    if isinstance(recorded, dict) and isinstance(live, dict):
        if recorded.keys() != live.keys():
            return [f"{path}: keys {sorted(live)} instead of {sorted(recorded)}"]
        return [
            found
            for key in recorded
            for found in differences(recorded[key], live[key], exact=exact, path=f"{path}.{key}")
        ]
    if isinstance(recorded, list) and isinstance(live, list):
        if len(recorded) != len(live):
            return [f"{path}: {len(live)} items instead of {len(recorded)}"]
        return [
            found
            for index, (a, b) in enumerate(zip(recorded, live, strict=True))
            for found in differences(a, b, exact=exact, path=f"{path}[{index}]")
        ]
    return _leaf_differences(recorded, live, exact=exact, path=path)


def _leaf_differences(recorded: Any, live: Any, *, exact: bool, path: str) -> list[str]:
    if recorded is None or live is None:
        return [] if recorded is live else [f"{path}: {live!r} instead of {recorded!r}"]
    measure = path.rsplit(".", 1)[-1] in MEASURES
    both_numbers = all(isinstance(v, int | float) and not isinstance(v, bool) for v in (recorded, live))
    if measure and both_numbers and not exact:
        close = math.isclose(recorded, live, rel_tol=TOLERANCE, abs_tol=1e-9)
        return [] if close else [f"{path}: {live} is not within 5 % of {recorded}"]
    if both_numbers and isinstance(recorded, float) and not measure:
        return []
    return [] if recorded == live else [f"{path}: {live!r} instead of {recorded!r}"]


def require_recorded_engine(client: httpx.Client) -> dict[str, Any]:
    """The engine's /status; stops the whole run when it is not the Valhalla the answers were recorded for."""
    recorded_version = recording("status")["response"]["version"]
    status: dict[str, Any] = client.get("/status").json()
    if status.get("version") != recorded_version:
        pytest.exit(
            f"recorded for Valhalla {recorded_version}, found {status.get('version')} - re-record the answers",
            returncode=2,
        )
    return status


@dataclass(frozen=True)
class Engine:
    client: httpx.Client
    exact: bool  # the live tileset is the recorded one


def _replaying() -> Iterator[httpx.Client]:
    with respx.mock(base_url=REPLAY_URL, assert_all_called=False) as router:
        router.get("/status").respond(json=recording("status")["response"])
        for name in RECORDED_QUESTIONS:
            recorded = recording(name)
            router.post(recorded["endpoint"], json=recorded["request"]).respond(
                recorded["status"], json=recorded["response"]
            )
        with httpx.Client(base_url=REPLAY_URL) as client:
            yield client


@pytest.fixture(
    params=[
        pytest.param("replay", id="replay"),
        pytest.param("live", id="live", marks=[pytest.mark.requires_external, pytest.mark.real_provider]),
    ]
)
def engine(request: pytest.FixtureRequest) -> Iterator[Engine]:
    url = request.config.getoption("--valhalla-url")
    if (request.param == "live") != bool(url):
        pytest.skip("live checks need --valhalla-url; without it the recordings are replayed")
    if request.param == "replay":
        for client in _replaying():
            yield Engine(client, exact=True)
        return
    with httpx.Client(base_url=url, timeout=120) as client:
        status = require_recorded_engine(client)
        yield Engine(client, exact=status["tileset_last_modified"] == recording("status")["tileset_last_modified"])


def test_the_engine_is_the_valhalla_the_answers_were_recorded_for(engine: Engine) -> None:
    status = require_recorded_engine(engine.client)

    assert status["version"] == "3.9.1"
    assert isinstance(status["tileset_last_modified"], int)


def test_a_different_valhalla_version_stops_the_run_with_a_clear_line() -> None:
    with respx.mock(base_url=REPLAY_URL) as router:
        router.get("/status").respond(json={"version": "3.10.0", "tileset_last_modified": 1})
        with httpx.Client(base_url=REPLAY_URL) as client, pytest.raises(pytest.exit.Exception) as stopped:
            require_recorded_engine(client)

    assert stopped.value.msg == "recorded for Valhalla 3.9.1, found 3.10.0 - re-record the answers"


@pytest.mark.parametrize("name", RECORDED_QUESTIONS)
def test_the_engine_answers_a_recorded_question_as_recorded(engine: Engine, name: str) -> None:
    recorded = recording(name)

    answer = engine.client.post(recorded["endpoint"], json=recorded["request"])

    assert answer.status_code == recorded["status"]
    assert differences(recorded["response"], answer.json(), exact=engine.exact) == []


@pytest.mark.parametrize(
    ("recorded", "live", "exact", "expected"),
    [
        ({"time": 100}, {"time": 100}, True, 0),
        ({"time": 100}, {"time": 101}, True, 1),
        ({"time": 100}, {"time": 104}, False, 0),
        ({"distance": 100.0}, {"distance": 106.0}, False, 1),
        ({"time": 100, "cost": 5.5}, {"time": 100, "cost": 9.9}, True, 0),
        ({"time": None, "distance": None}, {"time": 3, "distance": 1.0}, False, 2),
        ({"error_code": 170}, {"error_code": 171}, False, 1),
        ({"cells": [1, 2]}, {"cells": [1]}, False, 1),
        ({"a": 1}, {"b": 1}, False, 1),
    ],
)
def test_the_comparison_tells_agreement_from_drift(recorded: Any, live: Any, exact: bool, expected: int) -> None:
    assert len(differences(recorded, live, exact=exact)) == expected


def test_a_live_run_without_run_external_is_refused() -> None:
    command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--valhalla-url", "http://127.0.0.1:1"]

    refused = subprocess.run(
        [*command, "tests/contract/routing_port/test_engine_recordings.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert refused.returncode != 0
    assert "--valhalla-url needs --run-external" in refused.stdout + refused.stderr

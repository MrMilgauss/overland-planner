"""Layer 1 of `make contract-live` (D235): the recorded Valhalla 3.9.1 answers against the engine, raw questions only.

Every check posts a recorded request and compares the answer with the recording. With `--valhalla-url` (and
`--run-external`) the engine is the live one; without it the same checks replay the recordings through respx.
What the replay in CI proves: the questions the checks ask are the recorded ones and the comparison code behaves as
written. It cannot detect drift of the engine: the answers it compares are the recordings themselves. The live run
(`make contract-live`) is the only drift check. Layer 2, the routing-port suite through the planner's adapter, is
slice 06a.

Live, `--expect-tileset-modified N` names the map data the engine must serve (`make contract-live` reads it from
tiles.log): another `tileset_last_modified` stops the run, and the session says which one was checked and whether
distances were compared exactly or within 5 %.

Comparison, leaf by leaf: both leaves are of the same kind (null, bool, integer, float, string) or it is a difference.
Strings, bools, integers and nulls are always compared exactly (HTTP status, error code and message, key sets, list
lengths, null cells, the route polyline). Time, distance and length are exact when the live tileset is the recorded
one (same `tileset_last_modified`), else within 5 %. Every other float (cost, heading, snapped coordinates) is exact
on the recorded tileset and only has to be a float otherwise.
The answer's top-level `warnings` are the engine's notes on how it answered (for example "CostMatrix turned off
destination-only on a second pass"): they depend on its configuration, not on the roads, so they are not compared, on
either side (D242, found by the first live run).
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


# The engine's own notes about how it answered (D242); never part of the answer.
ADVISORY = frozenset({"warnings"})


def differences(recorded: Any, live: Any, *, exact: bool, path: str = "$") -> list[str]:
    """Where `live` departs from `recorded`; empty when the answers agree under the rules of the module docstring."""
    if isinstance(recorded, dict) and isinstance(live, dict):
        compared = recorded.keys() - ADVISORY if path == "$" else recorded.keys()
        if compared != (live.keys() - ADVISORY if path == "$" else live.keys()):
            return [f"{path}: keys {sorted(live)} instead of {sorted(recorded)}"]
        return [
            found
            for key in recorded
            if key in compared
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


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    for kind, types in (("bool", bool), ("integer", int), ("float", float), ("string", str), ("list", list)):
        if isinstance(value, types):
            return kind
    return "object"


def _leaf_differences(recorded: Any, live: Any, *, exact: bool, path: str) -> list[str]:
    kind = _kind(recorded)
    if kind != _kind(live):
        return [f"{path}: {live!r} is {_kind(live)}, recorded {kind} {recorded!r}"]
    if recorded == live:
        return []
    measure = path.rsplit(".", 1)[-1] in MEASURES
    if measure and not exact and kind in ("integer", "float"):
        close = math.isclose(recorded, live, rel_tol=TOLERANCE, abs_tol=1e-9)
        return [] if close else [f"{path}: {live} is not within 5 % of {recorded}"]
    if kind == "float" and not measure and not exact:
        return []
    return [f"{path}: {live!r} instead of {recorded!r}"]


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


def require_expected_tileset(status: dict[str, Any], expected: str | None) -> None:
    """Stops the whole run when the engine serves other map data than the one `--expect-tileset-modified` names."""
    live = status["tileset_last_modified"]
    if expected is not None and str(live) != expected:
        pytest.exit(f"the engine serves map data {live}, expected {expected}", returncode=2)


def checked_line(live: Any, *, exact: bool) -> str:
    return (
        f"contract-live: checked tileset_last_modified {live}; "
        f"distances compared {'exactly' if exact else 'within 5 %'}"
    )


_ANNOUNCED: set[str] = set()


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
        require_expected_tileset(status, request.config.getoption("--expect-tileset-modified"))
        exact = status["tileset_last_modified"] == recording("status")["tileset_last_modified"]
        line = checked_line(status["tileset_last_modified"], exact=exact)
        reporter = request.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None and line not in _ANNOUNCED:
            _ANNOUNCED.add(line)
            reporter.write_line(line)
        yield Engine(client, exact=exact)


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


def test_other_map_data_than_the_expected_stops_the_run_with_a_clear_line() -> None:
    with pytest.raises(pytest.exit.Exception) as stopped:
        require_expected_tileset({"tileset_last_modified": 1700000000}, "1793560782")

    assert stopped.value.msg == "the engine serves map data 1700000000, expected 1793560782"


@pytest.mark.parametrize("expected", [None, "1793560782"])
def test_the_expected_map_data_or_no_expectation_lets_the_run_go_on(expected: str | None) -> None:
    require_expected_tileset({"tileset_last_modified": 1793560782}, expected)


@pytest.mark.parametrize(("live", "exact", "words"), [(1793560782, True, "exactly"), (1800000000, False, "within 5 %")])
def test_the_session_says_which_map_data_was_checked_and_how_distances_were_compared(
    live: int, exact: bool, words: str
) -> None:
    line = checked_line(live, exact=exact)

    assert f"tileset_last_modified {live}" in line and f"distances compared {words}" in line


class _Status(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps({"version": "3.9.1", "tileset_last_modified": 1700000000}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _pytest_run(*options: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *options,
         "tests/contract/routing_port/test_engine_recordings.py", "-k", "the_engine_is_the_valhalla"],
        cwd=REPO, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip


def test_a_live_run_against_other_map_data_than_expected_stops_and_one_against_the_expected_says_what_it_checked() -> (
    None
):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Status)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    live = ("--run-external", "--valhalla-url", f"http://127.0.0.1:{server.server_address[1]}")
    try:
        stopped = _pytest_run(*live, "--expect-tileset-modified", "1793560782")
        accepted = _pytest_run(*live, "--expect-tileset-modified", "1700000000")
    finally:
        server.shutdown()

    assert stopped.returncode != 0
    assert "the engine serves map data 1700000000, expected 1793560782" in stopped.stdout + stopped.stderr
    assert "tileset_last_modified 1700000000; distances compared within 5 %" in accepted.stdout


def test_an_expectation_without_a_live_engine_is_refused() -> None:
    refused = _pytest_run("--expect-tileset-modified", "1793560782")

    assert refused.returncode != 0
    assert "--expect-tileset-modified needs --valhalla-url" in refused.stdout + refused.stderr


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
        ({"time": 100, "cost": 5.5}, {"time": 100, "cost": 9.9}, True, 1),
        ({"time": 100, "cost": 5.5}, {"time": 100, "cost": 9.9}, False, 0),
        ({"cost": 5.5}, {"cost": "5.5"}, False, 1),
        ({"ok": False}, {"ok": 0}, True, 1),
        ({"ok": True}, {"ok": False}, False, 1),
        ({"n": 45}, {"n": 45.3}, False, 1),
        ({"name": "a"}, {"name": "b"}, False, 1),
        ({"a": {}}, {"a": []}, False, 1),
        ({"time": None, "distance": None}, {"time": 3, "distance": 1.0}, False, 2),
        ({"error_code": 170}, {"error_code": 171}, False, 1),
        ({"cells": [1, 2]}, {"cells": [1]}, False, 1),
        ({"a": 1}, {"b": 1}, False, 1),
        ({"a": 1}, {"a": 1, "warnings": [{"code": 400}]}, True, 0),
        ({"a": 1, "warnings": [{"code": 400}]}, {"a": 1}, True, 0),
        ({"a": 1, "warnings": [{"code": 400}]}, {"a": 2, "warnings": []}, True, 1),
        ({"cell": {"a": 1}}, {"cell": {"a": 1, "warnings": []}}, True, 1),
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

"""Composition-root wiring (driving port: `create_app`, and the production `uvicorn --factory` command).

Integration level: single examples verify wiring (settings source, event log, clock), not input invariants.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from overland_planner.bootstrap.settings import InvalidSettingsError
from tests.common.fakes import FakeClock

REPO_ROOT = Path(__file__).resolve().parents[3]
FACTORY = "overland_planner.bootstrap.app_factory:create_app"


def _json_lines(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _started(text: str) -> list[dict[str, Any]]:
    return [record for record in _json_lines(text) if record.get("event") == "app.started"]


def test_create_app_reads_os_environ_when_given_no_mapping(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PLANNER_GIT_SHA", "0123456789ab")
    monkeypatch.setenv("ROUTING_PROVIDER", "mock")

    create_app()

    (started,) = _started(capsys.readouterr().out)
    assert started["app_version"] == "0123456789ab"


def test_create_app_given_a_mapping_reads_only_that_mapping(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PLANNER_GIT_SHA", "from-process-env")
    monkeypatch.setenv("ROUTING_PROVIDER", "valhalla")  # would be refused if the process environment were read

    create_app({"PLANNER_GIT_SHA": "from-mapping"})

    (started,) = _started(capsys.readouterr().out)
    assert started["app_version"] == "from-mapping"
    assert started["routing_provider"] == "mock"


def test_an_invalid_setting_stops_start_up_naming_the_setting() -> None:
    with pytest.raises(InvalidSettingsError, match="ROUTING_PROVIDER"):
        create_app({"ROUTING_PROVIDER": "valhalla"})


def test_every_event_is_one_json_line_with_utc_timestamp(capsys: pytest.CaptureFixture[str]) -> None:
    clock = FakeClock(datetime(2026, 11, 2, 19, 30, 15, 250_000, tzinfo=UTC))

    create_app({"PLANNER_GIT_SHA": "abc"}, external=ExternalPorts(clock=clock))

    records = _json_lines(capsys.readouterr().out)  # every stdout line must parse as one JSON object
    assert records, "no event was logged"
    for record in records:
        assert isinstance(record["event"], str)
        assert datetime.fromisoformat(record["ts"]) == clock.now()
        assert record["ts"].endswith("Z") or record["ts"].endswith("+00:00")


def _start_server_once(environ: dict[str, str]) -> str:
    """Run the production command until the app has started, stop it, and return its whole stdout."""
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory", FACTORY, "--host", "127.0.0.1", "--port", "0"],
        cwd=REPO_ROOT,
        env=environ,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stderr is not None
    deadline = time.monotonic() + 30
    for line in process.stderr:  # uvicorn reports readiness on stderr
        if "Application startup complete" in line or time.monotonic() > deadline:
            break
    process.terminate()
    stdout, stderr = process.communicate(timeout=15)
    assert process.returncode in (0, -15), stderr
    return stdout


def test_each_start_logs_one_app_started_line(tmp_path: Path) -> None:
    import os

    environ = {k: v for k, v in os.environ.items() if not k.startswith(("PLANNER_", "ROUTING_"))}
    environ.update({"PYTHONUNBUFFERED": "1", "DATA_DIR": str(tmp_path), "PLANNER_GIT_SHA": "0123456789ab"})

    for start in (1, 2):
        started = _started(_start_server_once(environ))
        assert len(started) == 1, f"start {start}: expected one app.started line, found {len(started)}"
        assert started[0]["app_version"] == "0123456789ab"
        assert started[0]["routing_provider"] == "mock"
        assert started[0]["python_version"] == platform.python_version()

"""Composition-root wiring (driving port: `create_app`, and the production `uvicorn --factory` command).

Integration level: single examples verify wiring (settings source, event log, clock), not input invariants.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from overland_planner.bootstrap.startup import StartupRefusedError
from tests.common.fakes import FakeClock

REPO_ROOT = Path(__file__).resolve().parents[3]
FACTORY = "overland_planner.bootstrap.app_factory:create_app"


@pytest.fixture
def data_dir() -> Iterator[Path]:
    """A fresh DATA_DIR under the workspace, never the OS temp folder (D182), removed after the test."""
    root = Path(os.environ.get("PLANNER_TEST_WORKSPACE", REPO_ROOT / ".data")) / "integration"
    folder = root / uuid.uuid4().hex[:12] / "data"
    folder.mkdir(parents=True)
    yield folder
    shutil.rmtree(folder.parent, ignore_errors=True)


def _json_lines(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _started(text: str) -> list[dict[str, Any]]:
    return [record for record in _json_lines(text) if record.get("event") == "app.started"]


def test_create_app_reads_os_environ_when_given_no_mapping(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], data_dir: Path
) -> None:
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("PLANNER_GIT_SHA", "0123456789ab")
    monkeypatch.setenv("ROUTING_PROVIDER", "mock")

    create_app()

    (started,) = _started(capsys.readouterr().out)
    assert started["app_version"] == "0123456789ab"


def test_create_app_given_a_mapping_reads_only_that_mapping(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], data_dir: Path
) -> None:
    monkeypatch.setenv("PLANNER_GIT_SHA", "from-process-env")
    monkeypatch.setenv("ROUTING_PROVIDER", "valhalla")  # would be refused if the process environment were read

    create_app({"PLANNER_GIT_SHA": "from-mapping", "DATA_DIR": str(data_dir)})

    (started,) = _started(capsys.readouterr().out)
    assert started["app_version"] == "from-mapping"
    assert started["routing_provider"] == "mock"


def test_an_invalid_setting_refuses_start_up_naming_the_setting(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(StartupRefusedError) as refused:
        create_app({"ROUTING_PROVIDER": "valhalla"})

    assert (refused.value.code, refused.value.component) == (1, "settings")
    (line,) = _json_lines(capsys.readouterr().out)
    assert (line["event"], line["component"]) == ("health.startup.refused", "settings")
    assert "ROUTING_PROVIDER" in line["reason"]


def test_every_event_is_one_json_line_with_utc_timestamp(capsys: pytest.CaptureFixture[str], data_dir: Path) -> None:
    clock = FakeClock(datetime(2026, 11, 2, 19, 30, 15, 250_000, tzinfo=UTC))

    create_app({"PLANNER_GIT_SHA": "abc", "DATA_DIR": str(data_dir)}, external=ExternalPorts(clock=clock))

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


def test_each_start_logs_one_app_started_line(data_dir: Path) -> None:
    environ = {k: v for k, v in os.environ.items() if not k.startswith(("PLANNER_", "ROUTING_"))}
    environ.update({"PYTHONUNBUFFERED": "1", "DATA_DIR": str(data_dir), "PLANNER_GIT_SHA": "0123456789ab"})

    for start in (1, 2):
        started = _started(_start_server_once(environ))
        assert len(started) == 1, f"start {start}: expected one app.started line, found {len(started)}"
        assert started[0]["app_version"] == "0123456789ab"
        assert started[0]["routing_provider"] == "mock"
        assert started[0]["python_version"] == platform.python_version()
        assert started[0]["alembic_revision"] == "0004"

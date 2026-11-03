"""`LocalFileStore` start-up probe on a real folder (brief §6, ADR-011): write, fsync, rename, read back, delete.

Integration level: single examples on the real filesystem, under the workspace and never the OS temp folder (D182).
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from overland_planner.adapters.files.local_file_store import LocalFileStore
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from overland_planner.bootstrap.startup import StartupRefusedError
from tests.common.fakes import FakeClock, FakeMountTable

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def data_dir() -> Iterator[Path]:
    root = Path(os.environ.get("PLANNER_TEST_WORKSPACE", REPO_ROOT / ".data")) / "integration"
    folder = root / uuid.uuid4().hex[:12] / "data"
    folder.mkdir(parents=True)
    yield folder
    for path in (folder, *folder.rglob("*")):
        if path.is_dir():
            path.chmod(0o755)
    shutil.rmtree(folder.parent, ignore_errors=True)


def test_the_round_trip_succeeds_and_leaves_no_probe_file(data_dir: Path) -> None:
    assert LocalFileStore(data_dir).probe() == ProbeResult(outcome="ok")
    assert list((data_dir / "tmp").iterdir()) == []


def test_a_scratch_folder_that_cannot_be_written_is_fatal(data_dir: Path) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("a read-only folder cannot be simulated as root")
    (data_dir / "tmp").mkdir(mode=0o555)

    assert LocalFileStore(data_dir).probe() == ProbeResult(outcome="fatal", reason="file_store_not_writable")


def test_the_planner_refuses_to_start_naming_the_file_store(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (data_dir / "tmp").write_text("a file where the scratch folder belongs")  # the database itself works

    with pytest.raises(StartupRefusedError) as refused:
        create_app(
            {"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "mock"},
            external=ExternalPorts(clock=FakeClock(), mount_table=FakeMountTable()),
        )

    assert (refused.value.code, refused.value.component) == (1, "file_store")
    refusals = [r for r in map(json.loads, capsys.readouterr().out.splitlines()) if r["event"].endswith("refused")]
    assert [(r["component"], r["reason"]) for r in refusals] == [("file_store", "file_store_not_writable")]

"""`LocalFileStore` reads of canonical points on a real folder (ADR-009, ADR-018): bytes as stored, per version.

Integration level: single examples on the real filesystem, under the workspace and never the OS temp folder (D182).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from overland_planner.adapters.files.local_file_store import LocalFileStore
from overland_planner.application.ports.file_store import CanonicalPointsMissing
from tests.common.workspace import workspace_data_dir

FIRST = b'{"points":[[45.0,7.0,null],[45.1,7.1,1200.5]]}'
SECOND = b'{"points":[[45.1,7.1,1200.5],[45.0,7.0,null]]}'


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        yield folder


def test_canonical_points_are_read_back_byte_identical_for_their_own_version(data_dir: Path) -> None:
    store = LocalFileStore(data_dir)
    store.keep_canonical_points("t1", 1, FIRST)
    store.keep_canonical_points("t1", 2, SECOND)

    assert store.read_canonical_points("t1", 1) == FIRST
    assert store.read_canonical_points("t1", 2) == SECOND


def test_a_missing_file_is_a_typed_outcome_whether_the_version_or_the_whole_track_is_gone(data_dir: Path) -> None:
    store = LocalFileStore(data_dir)
    store.keep_canonical_points("t1", 1, FIRST)
    (data_dir / "files/tracks/t2").mkdir()
    (data_dir / "files/tracks/t2/canonical.v1.json").write_bytes(SECOND)
    (data_dir / "files/tracks/t2/canonical.v1.json").unlink()

    assert store.read_canonical_points("t1", 2) == CanonicalPointsMissing()  # no such version
    assert store.read_canonical_points("t2", 1) == CanonicalPointsMissing()  # the file vanished
    assert store.read_canonical_points("no-such-track", 1) == CanonicalPointsMissing()
    assert not (data_dir / "files/tracks/no-such-track").exists(), "a read creates nothing"

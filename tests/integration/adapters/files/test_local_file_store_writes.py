"""`LocalFileStore` writes on a real folder (brief §9, ADR-018): originals by sha256, canonical points by version.

Integration level: single examples on the real filesystem, under the workspace and never the OS temp folder (D182).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from overland_planner.adapters.files.local_file_store import LocalFileStore
from tests.common.workspace import workspace_data_dir

GPX = b'<?xml version="1.0"?>\n<gpx version="1.1" creator="t"><trk><name>Assietta</name></trk></gpx>\r\n'


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        yield folder


def _files(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


def test_an_original_is_kept_byte_identical_once_under_its_sha256(data_dir: Path) -> None:
    store = LocalFileStore(data_dir)
    sha256 = hashlib.sha256(GPX).hexdigest()

    store.keep_original(sha256, GPX)
    store.keep_original(sha256, GPX)

    assert _files(data_dir) == [f"files/originals/{sha256}.gpx"]
    assert (data_dir / "files" / "originals" / f"{sha256}.gpx").read_bytes() == GPX


def test_canonical_points_are_written_per_track_and_version_through_the_scratch_folder(data_dir: Path) -> None:
    store = LocalFileStore(data_dir)

    store.keep_canonical_points("t1", 1, b'{"points":[[45.0,7.0,null]]}')

    assert _files(data_dir) == ["files/tracks/t1/canonical.v1.json"]
    assert (data_dir / "files/tracks/t1/canonical.v1.json").read_bytes() == b'{"points":[[45.0,7.0,null]]}'
    assert (data_dir / "tmp").is_dir()  # the write went through DATA_DIR/tmp, which is left empty

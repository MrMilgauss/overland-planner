"""The recorded Valhalla 3.9.1 answers are byte-for-byte what SPIKE-2R committed (D235): the manifest pins them."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "valhalla-3.9.1"
MANIFEST = FIXTURES / "MANIFEST.sha256"


def _manifest() -> dict[str, str]:
    assert MANIFEST.is_file(), "MANIFEST.sha256 missing"
    pairs = (line.split("  ", 1) for line in MANIFEST.read_text().splitlines() if line.strip())
    return {name: digest for digest, name in pairs}


def test_every_recording_matches_the_manifest_and_the_manifest_lists_every_recording() -> None:
    recordings = {path.name for path in FIXTURES.iterdir() if path.name != MANIFEST.name}
    listed = _manifest()

    assert recordings, "no recordings"
    assert set(listed) == recordings
    changed = [
        name for name, digest in listed.items() if hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() != digest
    ]
    assert changed == []


def test_the_recordings_were_made_by_valhalla_3_9_1() -> None:
    status = json.loads((FIXTURES / "status.json").read_text())

    assert status["valhalla"] == "3.9.1" and status["response"]["version"] == "3.9.1"

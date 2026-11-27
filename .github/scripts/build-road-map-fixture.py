#!/usr/bin/env python3
"""Build the fixture road map of CI job 7 (and of a local run) under the folder given as the one argument.

  <dir>/volume/tilesets/20261127/   road-map.json and outlines/*.poly of the eight regions, map date 27 Nov 2026
  <dir>/changes/                    empty, world-writable: the planner (uid 10001) and the specs write notes

Mounted by deploy/compose.ci.yaml; the specs read `ROAD_MAP_FIXTURE_DIR/changes`. Run with `uv run python`.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.acceptance.overland_route_planner_mvp.steps.road_map_fakes import build_volume
from tests.acceptance.overland_route_planner_mvp.steps.road_map_steps import EIGHT

TILESET = "20261127"


def main(target: Path) -> None:
    build_volume(target / "volume", {TILESET: (list(EIGHT), datetime(2026, 11, 27, 12, tzinfo=UTC))})
    changes = target / "changes"
    changes.mkdir(parents=True, exist_ok=True)
    changes.chmod(0o777)
    for folder in (target / "volume").rglob("*"):
        folder.chmod(0o755 if folder.is_dir() else 0o644)


if __name__ == "__main__":
    main(Path(sys.argv[1]))

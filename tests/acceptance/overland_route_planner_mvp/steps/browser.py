"""Marco in a real browser (policy: Driving, Browser UI row): the `@ui` scenario runs a Playwright spec against the
real planner server and reads back what the browser showed.

Playwright is TypeScript here (`tests/e2e/`), so one run covers the scenario's browser actions; the step definitions
record the actions and assert on what comes back. CI job 7 and `make e2e-local` skip the spec, it needs these settings.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
WEB_DIR = REPO_ROOT / "web"
RUN_TIMEOUT_S = 240.0


@dataclass(frozen=True)
class BrowserRun:
    """What the browser showed: one text per row of the itinerary, and the file it saved."""

    stop_rows: list[str]
    downloaded_name: str
    downloaded_file: Path


class FirstPlanJourney:
    def __init__(self, project_id: str, workdir: Path) -> None:
        self._project_id = project_id
        self._workdir = workdir

    def run(self, planner_url: str) -> BrowserRun:
        if not (WEB_DIR / "node_modules" / "@playwright" / "test").is_dir():
            pytest.skip("Playwright is not installed here (npm ci in web/)")
        self._workdir.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k != "E2E_START_LOCAL"}
        env.update(
            {
                "PLANNER_URL": planner_url,
                "FIRST_PLAN_PROJECT_ID": self._project_id,
                "FIRST_PLAN_RESULT_DIR": str(self._workdir),
                "NODE_PATH": str(WEB_DIR / "node_modules"),
                "NO_COLOR": "1",
            }
        )
        command = ["npx", "--no-install", "playwright", "test", "first-plan", "--project=chromium", "--reporter=line"]
        result = subprocess.run(
            command, cwd=WEB_DIR, env=env, capture_output=True, text=True, timeout=RUN_TIMEOUT_S, check=False
        )
        assert result.returncode == 0, (
            f"Marco could not finish in the browser:\n{(result.stdout + result.stderr)[-1500:]}"
        )
        seen: dict[str, Any] = json.loads((self._workdir / "result.json").read_text())
        return BrowserRun(seen["stop_rows"], seen["downloaded_name"], self._workdir / "downloaded.gpx")

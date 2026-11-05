"""Marco in a real browser (policy: Driving, Browser UI row): the `@ui` scenario runs a Playwright spec against the
real planner server and reads back what the browser showed.

Playwright is TypeScript here (`tests/e2e/`), so one run covers the scenario's browser actions; the step definitions
record the actions and assert on what comes back. CI job 7 and `make e2e-local` skip the spec, it needs these settings.

CI job 2 runs the scenario (D170), so there a missing Playwright is a failure; elsewhere it is a skip with the reason.
The real server serves whatever web/dist holds, so a missing or out-of-date build fails here rather than giving a
verdict on old code.
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
WEB_BUILD_FILES = ("index.html", "package-lock.json", "svelte.config.js", "vite.config.ts")
PLAYWRIGHT_MISSING = "Playwright is not installed here (npm ci in web/)"


@dataclass(frozen=True)
class BrowserRun:
    """What the browser showed: one text per row of the itinerary, and the file it saved."""

    stop_rows: list[str]
    downloaded_name: str
    downloaded_file: Path


def _require_playwright() -> None:
    if (WEB_DIR / "node_modules" / "@playwright" / "test").is_dir():
        return
    if os.environ.get("CI"):
        pytest.fail(PLAYWRIGHT_MISSING)
    pytest.skip(PLAYWRIGHT_MISSING)


def _require_current_web_page() -> None:
    page = WEB_DIR / "dist" / "index.html"
    if not page.is_file():
        pytest.fail("web/dist is missing: run `npx vite build` in web/")
    sources = [WEB_DIR / name for name in WEB_BUILD_FILES] + list((WEB_DIR / "src").rglob("*"))
    newest = max((source.stat().st_mtime for source in sources if source.is_file()), default=0.0)
    if page.stat().st_mtime < newest:
        pytest.fail("web/dist is older than the web sources: run `npx vite build` in web/")


class FirstPlanJourney:
    def __init__(self, project_id: str, workdir: Path) -> None:
        self._project_id = project_id
        self._workdir = workdir

    def run(self, planner_url: str) -> BrowserRun:
        _require_playwright()
        _require_current_web_page()
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

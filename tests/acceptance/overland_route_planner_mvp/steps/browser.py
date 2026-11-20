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


@dataclass(frozen=True)
class PhoneView:
    """What a phone screen showed (slice 02, `tests/e2e/phone-itinerary.spec.ts`): the page's own width against the
    screen's, each itinerary row with its text and horizontal extent, and the totals text (None when absent)."""

    screen_width: int
    page_width: int
    rows: list[dict[str, Any]]
    totals_text: str | None


class PhoneItineraryJourney:
    """Giulia opens a project's results on a 390 px wide phone screen (a viewport, not a real device)."""

    SCREEN_WIDTH = 390

    def __init__(self, project_id: str, workdir: Path) -> None:
        self._project_id = project_id
        self._workdir = workdir

    def run(self, planner_url: str) -> PhoneView:
        _require_playwright()
        _require_current_web_page()
        self._workdir.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k != "E2E_START_LOCAL"}
        env.update(
            {
                "PLANNER_URL": planner_url,
                "PHONE_PROJECT_ID": self._project_id,
                "PHONE_SCREEN_WIDTH": str(self.SCREEN_WIDTH),
                "PHONE_RESULT_DIR": str(self._workdir),
                "NODE_PATH": str(WEB_DIR / "node_modules"),
                "NO_COLOR": "1",
            }
        )
        command = [
            "npx", "--no-install", "playwright", "test", "phone-itinerary", "--project=chromium", "--reporter=line"
        ]  # fmt: skip
        result = subprocess.run(
            command, cwd=WEB_DIR, env=env, capture_output=True, text=True, timeout=RUN_TIMEOUT_S, check=False
        )
        assert result.returncode == 0, f"Giulia could not open the results:\n{(result.stdout + result.stderr)[-1500:]}"
        seen: dict[str, Any] = json.loads((self._workdir / "result.json").read_text())
        return PhoneView(seen["screen_width"], seen["page_width"], seen["rows"], seen["totals_text"])


@dataclass(frozen=True)
class MapView:
    """What a phone showed of the run map (slice 09, `tests/e2e/run-map.spec.ts`): the page's width against the
    screen's, the drawn canvas, the credit, the text of each numbered marker, and whether the map panned and zoomed."""

    screen_width: int
    page_width: int
    canvas_visible: bool
    credit_text: str
    numbers: list[str]
    panned: bool
    zoomed: bool


class PhoneMapJourney:
    """Giulia opens the map of a project's plan run on a 390 px wide phone screen (a Chromium viewport with touch, not
    a real device: WebKit headless is the weekly check)."""

    SCREEN_WIDTH = 390

    def __init__(self, project_id: str, workdir: Path) -> None:
        self._project_id = project_id
        self._workdir = workdir

    def run(self, planner_url: str) -> MapView:
        _require_playwright()
        _require_current_web_page()
        self._workdir.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k != "E2E_START_LOCAL"}
        env.update(
            {
                "PLANNER_URL": planner_url,
                "MAP_PROJECT_ID": self._project_id,
                "MAP_SCREEN_WIDTH": str(self.SCREEN_WIDTH),
                "MAP_RESULT_DIR": str(self._workdir),
                "NODE_PATH": str(WEB_DIR / "node_modules"),
                "NO_COLOR": "1",
            }
        )
        command = ["npx", "--no-install", "playwright", "test", "run-map", "--project=chromium", "--reporter=line"]
        result = subprocess.run(
            command, cwd=WEB_DIR, env=env, capture_output=True, text=True, timeout=RUN_TIMEOUT_S, check=False
        )
        assert result.returncode == 0, f"Giulia could not use the map:\n{(result.stdout + result.stderr)[-1500:]}"
        seen: dict[str, Any] = json.loads((self._workdir / "result.json").read_text())
        return MapView(
            seen["screen_width"],
            seen["page_width"],
            seen["canvas_visible"],
            seen["credit_text"],
            seen["numbers"],
            seen["panned"],
            seen["zoomed"],
        )


@dataclass(frozen=True)
class PoiClickView:
    """What the run map showed of a click (slice 09, step 10-05, `tests/e2e/run-map.spec.ts`): whether the click opened
    the name form, whether the form was gone afterwards, whether the new place shows in the trip list
    ("Your trip"), and what the "Click on map to add" control looked like."""

    form_shown: bool
    form_gone: bool
    listed: bool
    mode_seen: str
    metres_per_pixel: float


class PoiClickJourney:
    """Marco clicks the map of a project's plan run: `click` (at a place, then names it), `entry` (on an entry marker,
    then names it) or `cancel` (at a place, then Cancel). The browser is a 1280 px wide Chromium."""

    def __init__(self, project_id: str, workdir: Path) -> None:
        self._project_id = project_id
        self._workdir = workdir

    def run(self, planner_url: str, action: str, name: str, at: tuple[float, float]) -> PoiClickView:
        _require_playwright()
        _require_current_web_page()
        self._workdir.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k != "E2E_START_LOCAL"}
        env.update(
            {
                "PLANNER_URL": planner_url,
                "MAP_PROJECT_ID": self._project_id,
                "MAP_RESULT_DIR": str(self._workdir),
                "MAP_POI_ACTION": action,
                "MAP_POI_NAME": name,
                "MAP_POI_LAT": str(at[0]),
                "MAP_POI_LON": str(at[1]),
                "NODE_PATH": str(WEB_DIR / "node_modules"),
                "NO_COLOR": "1",
            }
        )
        command = [
            "npx",
            "--no-install",
            "playwright",
            "test",
            "run-map",
            "--project=chromium",
            "--reporter=line",
            "-g",
            "POI",
        ]
        result = subprocess.run(
            command, cwd=WEB_DIR, env=env, capture_output=True, text=True, timeout=RUN_TIMEOUT_S, check=False
        )
        assert result.returncode == 0, f"Marco could not click the map:\n{(result.stdout + result.stderr)[-1500:]}"
        seen: dict[str, Any] = json.loads((self._workdir / "result.json").read_text())
        return PoiClickView(
            seen["form_shown"], seen["form_gone"], seen["listed"], seen["mode_seen"], seen["metres_per_pixel"]
        )

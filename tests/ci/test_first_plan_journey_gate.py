"""The browser scenario of slice 01b cannot pass by skipping in CI, nor against an out-of-date web page (D170)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.acceptance.overland_route_planner_mvp.steps import browser
from tests.acceptance.overland_route_planner_mvp.steps.browser import FirstPlanJourney

OLDER, NEWER = 1_000_000_000, 2_000_000_000


def _file(path: Path, mtime: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    os.utime(path, (mtime, mtime))


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "web"
    directory.mkdir()
    monkeypatch.setattr(browser, "WEB_DIR", directory)
    return directory


@pytest.fixture
def browser_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Stands in for Playwright: records the settings of each run and reports what the browser would have shown."""
    runs: list[dict[str, str]] = []

    def run(_command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        env = kwargs["env"]
        runs.append(env)
        result = {"stop_rows": ["Start"], "downloaded_name": "plan.gpx"}
        (Path(env["FIRST_PLAN_RESULT_DIR"]) / "result.json").write_text(json.dumps(result))
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(browser.subprocess, "run", run)
    return runs


def _journey(web: Path) -> FirstPlanJourney:
    return FirstPlanJourney("project-1", web.parent / "browser")


def test_ci_fails_the_scenario_when_playwright_is_missing(
    web: Path, browser_runs: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CI", "true")

    # Catches both outcomes: a bare pytest.raises(fail) would let a regression to skip() report this test as skipped.
    with pytest.raises((pytest.fail.Exception, pytest.skip.Exception), match="Playwright is not installed") as outcome:
        _journey(web).run("http://planner")

    assert outcome.type is pytest.fail.Exception
    assert browser_runs == []


def test_outside_ci_a_missing_playwright_skips_with_the_reason(
    web: Path, browser_runs: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)

    with pytest.raises(pytest.skip.Exception, match=r"Playwright is not installed here \(npm ci in web/\)"):
        _journey(web).run("http://planner")

    assert browser_runs == []


@pytest.mark.parametrize("ci", [None, "true"])
@pytest.mark.parametrize(
    ("built_at", "source"),
    [
        (None, "src/App.svelte"),
        (OLDER, "src/lib/deep/Itinerary.svelte"),
        (OLDER, "index.html"),
        (OLDER, "package-lock.json"),
    ],
)
def test_a_missing_or_out_of_date_web_page_fails_the_scenario(
    web: Path,
    browser_runs: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    ci: str | None,
    built_at: int | None,
    source: str,
) -> None:
    (web / "node_modules" / "@playwright" / "test").mkdir(parents=True)
    _file(web / source, NEWER)
    if built_at is not None:
        _file(web / "dist" / "index.html", built_at)
    if ci is None:
        monkeypatch.delenv("CI", raising=False)
    else:
        monkeypatch.setenv("CI", ci)

    with pytest.raises(pytest.fail.Exception, match="npx vite build"):
        _journey(web).run("http://planner")

    assert browser_runs == []


def test_a_current_web_page_reaches_the_browser(web: Path, browser_runs: list[dict[str, str]]) -> None:
    (web / "node_modules" / "@playwright" / "test").mkdir(parents=True)
    _file(web / "src" / "App.svelte", OLDER)
    _file(web / "dist" / "index.html", NEWER)

    seen = _journey(web).run("http://planner")

    assert seen.stop_rows == ["Start"]
    assert seen.downloaded_name == "plan.gpx"
    assert [(run["PLANNER_URL"], run["FIRST_PLAN_PROJECT_ID"]) for run in browser_runs] == [
        ("http://planner", "project-1")
    ]

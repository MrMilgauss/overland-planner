"""Repository hygiene gates (slice 00a): GPX ignore rules (D178) and brief section 11 import contracts."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_GPX = "tests/acceptance/overland_route_planner_mvp/fixtures/gpx"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _git_ignored(paths: list[str]) -> set[str]:
    """Paths git would ignore (check-ignore --no-index evaluates the rules, tracked or not)."""
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=REPO_ROOT,
        input="\n".join(paths),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    return set(result.stdout.split())


@pytest.mark.parametrize(
    "path",
    ["export.gpx", "data/plan-2026.gpx", "src/overland_planner/out.gpx", "tests/acceptance/tmp.gpx"],
)
def test_gpx_outside_fixture_folders_is_ignored(path: str) -> None:
    assert _git_ignored([path]) == {path}


def test_fixture_gpx_files_stay_tracked() -> None:
    fixture_gpx = [
        "tests/fixtures/assietta.gpx",
        "tests/fixtures/gpx/nested/deep.gpx",
        *sorted(p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / ACCEPTANCE_GPX).glob("*.gpx")),
    ]
    assert len(fixture_gpx) > 2, "acceptance GPX fixtures missing"
    assert _git_ignored(fixture_gpx) == set()


def test_env_is_ignored_but_its_template_is_not() -> None:
    assert _git_ignored([".env", ".env.example"]) == {".env"}


def test_import_contracts_hold() -> None:
    lint_imports = shutil.which("lint-imports")
    assert lint_imports is not None, "import-linter (lint-imports) is not installed"
    result = subprocess.run(
        [lint_imports, "--config", "pyproject.toml"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for contract in (
        "Layers",
        "Domain forbidden",
        "Application forbidden",
        "Adapter independence",
        "Domain catalog",
        "Domain routing",
        "ortools only in adapters.solver",
    ):
        assert contract in result.stdout, f"contract '{contract}' not configured"

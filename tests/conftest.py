"""Suite-wide pytest configuration: Gherkin tag handling and the one-at-a-time gates (DISTILL D113).

- Tags become markers with hyphens replaced by underscores (`@slice-01a` -> `slice_01a`, `@real-io` -> `real_io`),
  so CI can select with `-m "not real_provider and not pi"`.
- `@pending` scenarios are skipped unless their slice is enabled with `--run-pending=slice-01a` (repeatable).
  DELIVER removes `@pending` from one scenario at a time.
- `@requires_external` scenarios are skipped unless `--run-external` is given (Pi, Docker, PC, live Valhalla).
- `--valhalla-url URL` points the recorded-answers checks (tests/contract/routing_port) at a live engine; it needs
  `--run-external`, and without it those checks replay the recordings. `--expect-tileset-modified N` names the map data
  (`tileset_last_modified`) that live engine must serve.
- `@manual` scenarios are always skipped here; their evidence is logged by hand (docs/demo/).
- Git isolation: pytest started inside a git hook (e.g. pre-push from a linked worktree) inherits GIT_DIR,
  GIT_INDEX_FILE, GIT_WORK_TREE...; tests that shell out to git would then act on the hook's repository. The
  session removes every repository-local GIT_* variable, so each git subprocess finds its repository from its cwd.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from hypothesis import Phase, settings


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("overland-planner acceptance")
    group.addoption(
        "--run-pending",
        action="append",
        default=[],
        metavar="SLICE",
        help="Also run @pending scenarios of this slice, e.g. --run-pending=slice-01a (repeatable).",
    )
    group.addoption(
        "--run-external",
        action="store_true",
        default=False,
        help="Run @requires_external scenarios (Pi, Docker, PC, live Valhalla).",
    )
    group.addoption(
        "--valhalla-url",
        default=None,
        metavar="URL",
        help="Ask the live Valhalla at URL the recorded questions (make contract-live); needs --run-external.",
    )
    group.addoption(
        "--expect-tileset-modified",
        default=None,
        metavar="N",
        help="With --valhalla-url: the tileset_last_modified the live engine must serve (from tiles.log).",
    )


_CONFIG: list[pytest.Config] = []


def pytest_configure(config: pytest.Config) -> None:
    _CONFIG.append(config)
    if config.getoption("--valhalla-url") and not config.getoption("--run-external"):
        raise pytest.UsageError("--valhalla-url needs --run-external: a live run is refused without it")
    if config.getoption("--expect-tileset-modified") and not config.getoption("--valhalla-url"):
        raise pytest.UsageError("--expect-tileset-modified needs --valhalla-url: there is no live engine to check")


def _marker_name(tag: str) -> str:
    return tag.replace("-", "_")


def pytest_bdd_apply_tag(tag: str, function: Callable[..., Any]) -> Callable[..., Any]:
    name = _marker_name(tag)
    if _CONFIG:  # register story/slice/type tags so they are known markers (no unknown-mark warnings)
        _CONFIG[-1].addinivalue_line("markers", f"{name}: Gherkin tag @{tag}")
    return getattr(pytest.mark, name)(function)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    enabled_slices = {_marker_name(s) for s in config.getoption("--run-pending")}
    run_external = config.getoption("--run-external")
    for item in items:
        names = {mark.name for mark in item.iter_markers()}
        if "manual" in names:
            item.add_marker(pytest.mark.skip(reason="manual check: evidence is logged by hand (docs/demo/)"))
            continue
        if "pending" in names and not (names & enabled_slices):
            slices = sorted(n for n in names if n.startswith("slice_"))
            item.add_marker(pytest.mark.skip(reason=f"pending: {', '.join(slices) or 'unsliced'} not enabled yet"))
            continue
        if "requires_external" in names and not run_external:
            item.add_marker(pytest.mark.skip(reason="requires_external: run with --run-external on the right host"))


# Always removed, even if `git rev-parse --local-env-vars` cannot run or lists fewer (older git).
_GIT_REPOSITORY_VARIABLES = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    }
)


def _git_repository_variables() -> frozenset[str]:
    """Every variable git treats as local to one repository (`git rev-parse --local-env-vars`), plus the fixed set."""
    try:
        listed = subprocess.run(
            ["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True, check=False, timeout=30
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        listed = []
    return _GIT_REPOSITORY_VARIABLES | frozenset(listed)


@pytest.fixture(scope="session", autouse=True)
def _git_subprocesses_use_their_own_repository() -> Iterator[None]:
    removed = {name: os.environ.pop(name) for name in _git_repository_variables() if name in os.environ}
    yield
    os.environ.update(removed)


# Hypothesis profiles (D97), selected with HYPOTHESIS_PROFILE (default dev).
settings.register_profile("dev", max_examples=100)
settings.register_profile("ci", max_examples=1_000, derandomize=True)
# mutation (step 07-13): no shrink phase. A mutant only has to fail, not fail minimally; with shrinking, a mutant that
# ends a plan job before it reaches a test's gate re-ran its failing example for up to 300 s, each run waiting out the
# 30 s gate deadline at 0 % CPU, so mutmut's wall timeout (about 9 min for PlanRequestJob.run) left the run stalled.
settings.register_profile(
    "mutation",
    max_examples=50,
    derandomize=True,
    phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.target),
)
# weekly.yml deep run (D86): ten times the CI examples with random seeds.
settings.register_profile("deep", max_examples=10_000, derandomize=False)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

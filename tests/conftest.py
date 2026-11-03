"""Suite-wide pytest configuration: Gherkin tag handling and the one-at-a-time gates (DISTILL D113).

- Tags become markers with hyphens replaced by underscores (`@slice-01a` -> `slice_01a`, `@real-io` -> `real_io`),
  so CI can select with `-m "not real_provider and not pi"`.
- `@pending` scenarios are skipped unless their slice is enabled with `--run-pending=slice-01a` (repeatable).
  DELIVER removes `@pending` from one scenario at a time.
- `@requires_external` scenarios are skipped unless `--run-external` is given (Pi, Docker, PC, live Valhalla).
- `@manual` scenarios are always skipped here; their evidence is logged by hand (docs/demo/).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import pytest
from hypothesis import settings


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


_CONFIG: list[pytest.Config] = []


def pytest_configure(config: pytest.Config) -> None:
    _CONFIG.append(config)


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


# Hypothesis profiles (D97), selected with HYPOTHESIS_PROFILE (default dev).
settings.register_profile("dev", max_examples=100)
settings.register_profile("ci", max_examples=1_000, derandomize=True)
settings.register_profile("mutation", max_examples=50, derandomize=True)
# weekly.yml deep run (D86): ten times the CI examples with random seeds.
settings.register_profile("deep", max_examples=10_000, derandomize=False)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

"""Fixtures and step registration for the overland-route-planner-mvp acceptance suite.

Placement (DISTILL D103): tests/acceptance/overland_route_planner_mvp/ holds the .feature files (scenario SSOT),
steps/ the domain step definitions, test_*.py the pytest-bdd bindings. Infrastructure per
docs/architecture/atdd-infrastructure-policy.md.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.acceptance.overland_route_planner_mvp.steps.catalog_steps import *  # noqa: F403
from tests.acceptance.overland_route_planner_mvp.steps.platform_steps import *  # noqa: F403
from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld
from tests.common.fakes import FakeClock, FakeMountTable


REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def data_dir() -> Iterator[Path]:
    """The planner's data folder, under the workspace and never under the OS temp folder (ADR-011 D121, review H-02):
    on many Linux hosts /tmp is tmpfs, which the persistence probe rightly reports as not persistent. Root: env
    PLANNER_TEST_WORKSPACE, else <repo>/.data (git-ignored; in CI the checkout under $GITHUB_WORKSPACE)."""
    root = Path(os.environ.get("PLANNER_TEST_WORKSPACE", REPO_ROOT / ".data")) / "acceptance"
    folder = root / uuid.uuid4().hex[:12] / "data"
    folder.mkdir(parents=True)
    yield folder
    folder.chmod(0o755)
    shutil.rmtree(folder.parent, ignore_errors=True)


@pytest.fixture
def planner_environ(data_dir: Path) -> dict[str, str]:
    """The planner's settings, using the documented .env keys (brief §12). Offline road map; small solver budget."""
    return {
        "DATA_DIR": str(data_dir),
        "ROUTING_PROVIDER": "mock",
        "LOG_LEVEL": "INFO",
        "SOLVER_BUDGET": "500",
    }


@pytest.fixture
def world(tmp_path: Path, data_dir: Path, planner_environ: dict[str, str]) -> Iterator[PlannerWorld]:
    state = PlannerWorld(
        tmp_path=tmp_path,
        data_dir=data_dir,
        environ=planner_environ,
        clock=FakeClock(),
        mount_table=FakeMountTable(),
    )
    yield state
    data_dir.chmod(0o755)
    state.shutdown()

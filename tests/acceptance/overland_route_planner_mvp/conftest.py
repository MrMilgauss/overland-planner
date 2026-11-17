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
from tests.acceptance.overland_route_planner_mvp.steps.direction_steps import *  # noqa: F403
from tests.acceptance.overland_route_planner_mvp.steps.performance_steps import *  # noqa: F403
from tests.acceptance.overland_route_planner_mvp.steps.plan_steps import *  # noqa: F403
from tests.acceptance.overland_route_planner_mvp.steps.platform_steps import *  # noqa: F403
from tests.acceptance.overland_route_planner_mvp.steps.retrace_steps import *  # noqa: F403
from tests.acceptance.overland_route_planner_mvp.steps.routing_steps import *  # noqa: F403
from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld
from tests.common.fakes import FakeClock, FakeMountTable
from tests.common.workspace import workspace_data_dir




@pytest.fixture
def data_dir() -> Iterator[Path]:
    """The planner's data folder, under the workspace, never the OS temp folder (`tests/common/workspace.py`)."""
    with workspace_data_dir("acceptance") as folder:
        yield folder


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

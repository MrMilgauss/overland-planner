"""pytest-bdd binding: the slice 12b scenarios checked at the HTTP API and the server process (US-26, D287).

The feature is `@slice-12b`, enabled in CI by `--run-pending=slice-12b` in PENDING_FLAGS (.github/workflows/ci.yml,
step 12-07, as slice 12 in step 11-08).
The `@ui` scenarios are checked by tests/e2e/trip-workflow.spec.ts (Playwright, CI job 7) and are not bound here.

Neither scenario plans, so neither is `solver_child`. The key guard runs the real server process (`wiring_e2e`), as its
slice 09 twin for the Terrain tiles; the settings rule itself is DELIVER's inner check in
tests/unit/bootstrap/test_settings.py and tests/integration/http/test_map_config.py.
"""

import pytest
from pytest_bdd import scenario

FEATURE = "slice-12b-trip-workflow.feature"


@pytest.mark.driving_port
@scenario(FEATURE, "The planner names the light base map and its credit and keeps the Terrain map")
def test_the_planner_names_the_light_base_map_and_keeps_the_terrain_map() -> None:
    """`GET /api/config/map`: `base_style_url` Positron, `base_attribution` its credit; the Terrain fields as before."""


@pytest.mark.driving_port
@pytest.mark.wiring_e2e
@scenario(FEATURE, "A light base map address carrying a private access key stops the planner at start-up")
def test_a_keyed_light_base_map_address_stops_the_planner_at_start_up() -> None:
    """The real server process refuses: one `health.startup.refused` line names MAP_BASE_STYLE_URL and `api_key`."""

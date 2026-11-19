"""Slice 12b steps at the HTTP API and the server process (US-26, D287, ADR-004 Amendment 1): the light base map.

`GET /api/config/map` gains `base_style_url` (default OpenFreeMap "Positron") and `base_attribution` (its credit, set by
the planner because the style carries none); `tile_url`, `attribution` and `max_zoom` keep their meaning, now the
Terrain map. `MAP_BASE_STYLE_URL` falls under the slice 09 tile guard: userinfo, a fragment or a key-like query
parameter refuses the start, naming the setting and the parameter, never its value.
The `@ui` scenarios of the feature are checked in tests/e2e/trip-workflow.spec.ts, not here.

No production module is imported: every step goes through a driving port (the HTTP API, the real server process), so
until DELIVER adds the two settings the Thens fail on what the planner answers or logs (a business reason), not on an
import. Reused from slice 09 (Pillar 2): "the planner settings choose the OpenTopoMap tiles with their attribution",
"Marco opens any map", "the map loads its tiles from OpenTopoMap", "the attribution ... is always shown", "Marco starts
the planner", "the planner refuses to start". Reading the map settings and a refused start change nothing Marco can
see (no planning universe to diff).
"""

from __future__ import annotations

from pytest_bdd import given, parsers, then

from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld

POSITRON_STYLE_URL = "https://tiles.openfreemap.org/styles/positron"
POSITRON_ATTRIBUTION = "© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors"
BASE_STYLE_SETTING = "MAP_BASE_STYLE_URL"
BASE_ATTRIBUTION_SETTING = "MAP_BASE_ATTRIBUTION"
# A made-up key on a made-up host: the repository is public, and the planner never fetches the style.
KEY_PARAMETER = "api_key"
KEY_VALUE = "not-a-real-key"
KEYED_STYLE_URL = f"https://maps.example.test/styles/calm.json?{KEY_PARAMETER}={KEY_VALUE}"
BASE_MAPS = {"Positron": POSITRON_STYLE_URL}


# ---------------------------------------------------------------------------------------------------- Given
@given("the planner settings leave the light base map to its default")
def given_the_settings_leave_the_light_base_map_to_its_default(world: PlannerWorld) -> None:
    """Neither base map key is set: the planner's own default answers (an empty value means the default too)."""
    assert world.planner is not None, "the planner settings were not chosen first"
    assert BASE_STYLE_SETTING not in world.environ and BASE_ATTRIBUTION_SETTING not in world.environ, (
        f"this world sets a light base map of its own: {world.environ.get(BASE_STYLE_SETTING)!r}"
    )


@given("the planner settings use a light base map address that carries a private access key")
def given_the_settings_carry_a_keyed_light_base_map_address(world: PlannerWorld) -> None:
    world.environ[BASE_STYLE_SETTING] = KEYED_STYLE_URL


# ----------------------------------------------------------------------------------------------------- Then
@then(
    parsers.re(
        r'the light base map is OpenFreeMap "(?P<style>[^"]+)" with the credit "(?P<credit>[^"]+)"',
    )
)
def then_the_light_base_map_is(world: PlannerWorld, style: str, credit: str) -> None:
    config = world.scratch["map_config"]
    assert "base_style_url" in config and "base_attribution" in config, (
        f"the map settings name no light base map (they hold {sorted(config)})"
    )
    assert config["base_style_url"] == BASE_MAPS[style], f"the light base map is {config['base_style_url']!r}"
    assert config["base_attribution"] == credit == POSITRON_ATTRIBUTION, (
        f"the light base map is credited {config['base_attribution']!r}"
    )


@then("the planner log names the light base map setting and the key's parameter, never the key itself")
def then_the_log_names_the_setting_and_parameter_never_the_key(world: PlannerWorld) -> None:
    record = world.last_start
    assert record is not None, "the planner was not started"
    (refusal,) = record.events("health.startup.refused")
    reason = str(refusal.get("reason", ""))
    assert refusal.get("component") == "settings", f"the refusal names {refusal.get('component')!r}, not the settings"
    assert BASE_STYLE_SETTING in reason and KEY_PARAMETER in reason, f"the refusal says {reason!r}"
    shown = "\n".join([*record.stdout, *record.stderr])
    assert KEY_VALUE not in shown, "the planner's output shows the private key"

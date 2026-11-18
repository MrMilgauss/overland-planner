"""pytest-bdd binding: slice 09 scenarios checked at the HTTP API (step 10-02) and in the browser. Since step 10-06 the
slice is enabled in CI (PENDING_FLAGS); the three scenarios that wait for slice 08 carry their own `@pending`.

The 11-stop reference run and the Unconfirmed-leg run solve in the solver child, so they are `solver_child` and pre-push
leaves them to CI job 2, as for slices 03b and 06a. The unavailable-shapes scenario plans on the real Valhalla adapter
against the synthetic engine (the one slice 06a uses), which then goes down.
"""

import pytest
from pytest_bdd import scenario

from tests.acceptance.overland_route_planner_mvp.steps.routing_steps import route_on_synthetic_valhalla
from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld

FEATURE = "slice-09-directional-map.feature"


@pytest.mark.solver_child
@scenario(FEATURE, "The map shows which way each trail is driven")
def test_the_map_shows_which_way_each_trail_is_driven() -> None:
    """Run #4 of the reference trip, 11 stops: lines in itinerary order, markers numbered 1 to 11."""


@pytest.mark.solver_child
@scenario(FEATURE, "A round trip shows one combined Start and End marker")
def test_a_round_trip_shows_one_combined_start_and_end_marker() -> None:
    """Casa Marco is Start and End: one `start_end` marker standing for stops 1 and 11."""


@pytest.fixture
def the_planner_routes_on_a_synthetic_valhalla(world: PlannerWorld) -> None:
    """The real Valhalla adapter, answered by a scripted engine that the scenario then takes down."""
    route_on_synthetic_valhalla(world)


@pytest.mark.solver_child
@scenario(FEATURE, "The map still shows the plan when road shapes are unavailable")
def test_the_map_still_shows_the_plan_when_road_shapes_are_unavailable(
    the_planner_routes_on_a_synthetic_valhalla: None,
) -> None:
    """The engine refuses connections after run #4: road legs straight and unavailable, tracks as driven."""


@pytest.mark.solver_child
@scenario(FEATURE, "Compromise legs stand out on the map")
def test_compromise_legs_stand_out_on_the_map() -> None:
    """An Unconfirmed leg and a retrace on the scripted road map: `level unconfirmed` and its reason, `kind retrace`."""


@pytest.mark.driving_port
@scenario(FEATURE, "The map uses Marco's chosen map tiles and always credits them")
def test_the_map_uses_marcos_chosen_map_tiles_and_always_credits_them() -> None:
    """The settings name the OpenTopoMap address and its attribution (the web's credit control: 10-04's Playwright)."""


@pytest.mark.solver_child
@pytest.mark.wiring_e2e
@scenario(FEATURE, "Giulia uses the map on her phone")
def test_giulia_uses_the_map_on_her_phone() -> None:
    """Plan run #4 on a real server, the map in a 390 px wide Chromium with touch (`tests/e2e/run-map.spec.ts`)."""


@pytest.mark.wiring_e2e
@scenario(FEATURE, "A map tile address carrying a private access key stops the planner at start-up")
def test_a_map_tile_address_carrying_a_private_access_key_stops_the_planner_at_start_up() -> None:
    """The real server process refuses to start: one `health.startup.refused` line names setting and parameter."""


@pytest.mark.solver_child
@pytest.mark.wiring_e2e
@scenario(FEATURE, "Marco adds a trailhead POI by clicking the map")
def test_marco_adds_a_trailhead_poi_by_clicking_the_map() -> None:
    """The run map in Chromium: "Click on map", a click at Susa, the name form, Add: the POI is where he clicked."""


@pytest.mark.solver_child
@pytest.mark.wiring_e2e
@scenario(FEATURE, "A POI at a trail entry can become the Start")
def test_a_poi_at_a_trail_entry_can_become_the_start() -> None:
    """A click next to an entry marker takes the marker's own coordinates; the planner takes that POI as the Start."""


@pytest.mark.solver_child
@pytest.mark.wiring_e2e
@scenario(FEATURE, "Cancelling the name prompt adds nothing")
def test_cancelling_the_name_prompt_adds_nothing() -> None:
    """Cancel closes the name form and the planner holds no new place."""


@pytest.mark.solver_child
@pytest.mark.wiring_e2e
@scenario(FEATURE, "A POI added on the map marks the plan stale")
def test_a_poi_added_on_the_map_marks_the_plan_stale() -> None:
    """The plan run computed before the click is Stale after it (the existing revision rule)."""

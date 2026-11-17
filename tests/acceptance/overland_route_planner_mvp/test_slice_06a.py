"""pytest-bdd binding: slice 06a scenarios (phase 09); the slice blocks in CI since step 09-11.

The three `@pi @real_provider @requires_external` scenarios drive the live engine on the Pi through a remote planner
(PLANNER_PERF_URL, the credentials from the environment): they are skipped without --run-external and run only through
make acceptance-pi (the 3-minute one reads the report of make perf-pi MODE=e2e named by PERF_REPORT).

"A place far from any road" plans four times on the offline road map before it fails at the reachability check; its
first plan is a real solve in the solver child, so pre-push leaves it to CI job 2.
"""

import pytest
from pytest_bdd import scenario

from tests.acceptance.overland_route_planner_mvp.steps.routing_steps import route_on_synthetic_valhalla
from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld

FEATURE = "slice-06a-valhalla-on-the-pi.feature"
REFERENCE_PLACES = ("Cortina d'Ampezzo", "Lago di Braies", "Aosta", "Bardonecchia", "Cuneo", "Rochemolles")


@pytest.mark.solver_child
@scenario(FEATURE, "A place far from any road fails the plan and names it")
def test_a_place_far_from_any_road_fails_the_plan_and_names_it() -> None:
    """Off-network place scripted on the offline road map; ends at the reachability check."""


@pytest.fixture
def a_reference_trip_with_an_armable_road_map(world: PlannerWorld) -> None:
    """Plan run #4 is computed on 8 items other than the anchors (the day trip has 2), on a road map the scenario can
    arm: the far-place scenario's own world is untouched."""
    world.scratch["reference_places"] = REFERENCE_PLACES


@pytest.mark.solver_child
@scenario(FEATURE, "Road legs found before the routing engine failed are kept for next time")
def test_road_legs_found_before_the_routing_engine_failed_are_kept_for_next_time(
    a_reference_trip_with_an_armable_road_map: None,
) -> None:
    """Five legs answered, the sixth call fails: the job ends failed, no run, and the five legs are served next time."""


@pytest.fixture
def the_planner_routes_on_a_synthetic_valhalla(world: PlannerWorld) -> None:
    """The real Valhalla adapter, answered by a scripted engine that the scenario then makes fail (D247, D248)."""
    route_on_synthetic_valhalla(world)


@pytest.mark.solver_child
@scenario(FEATURE, "Routing engine unreachable leaves the project intact")
def test_routing_engine_unreachable_leaves_the_project_intact(the_planner_routes_on_a_synthetic_valhalla: None) -> None:
    """Run #4 is computed on the engine, which then refuses connections: the press is refused, nothing changes."""


@pytest.mark.solver_child
@scenario(FEATURE, "Plans are refused while the routing engine is not the version the planner was checked with")
def test_plans_are_refused_while_the_routing_engine_is_not_the_expected_version(
    the_planner_routes_on_a_synthetic_valhalla: None,
) -> None:
    """The engine now reports 3.10.0: the press is refused as not ready and the health detail names both versions."""


@pytest.mark.solver_child
@scenario(FEATURE, "The routing engine is still loading its map data")
def test_the_routing_engine_is_still_loading_its_map_data(the_planner_routes_on_a_synthetic_valhalla: None) -> None:
    """The engine answers /status and 503 on the matrix: refused as not ready, and the diagnostics count it."""


@pytest.mark.solver_child
@scenario(FEATURE, "Marco switches the objective to road time")
def test_marco_switches_the_objective_to_road_time(a_reference_trip_with_an_armable_road_map: None) -> None:
    """Run #4 was minimised on road distance; the switch asks no new leg and the next run says road time."""


@scenario(FEATURE, "New projects minimise road distance by default")
def test_new_projects_minimise_road_distance_by_default() -> None:
    """A project made now has objective `distance`."""


@pytest.fixture
def the_planner_log_is_listened_to(world: PlannerWorld, capsys: pytest.CaptureFixture[str]) -> None:
    """The planner writes its log lines to standard output: they are captured from before it starts."""
    world.scratch["capsys"] = capsys


@pytest.mark.solver_child
@scenario(FEATURE, "Marco's password is never shown")
def test_marcos_password_is_never_shown(the_planner_log_is_listened_to: None) -> None:
    """Plan run #4 is computed and exported with the household password set: it is in no answer, log line or file."""


@scenario(FEATURE, "Marco plans with Valhalla on his Pi")
def test_marco_plans_with_valhalla_on_his_pi() -> None:
    """Live: Torino to Susa on the Pi's engine, in a `__demo` project of its own."""


@scenario(FEATURE, "A trail entry reached by a forest track is Confirmed")
def test_a_trail_entry_reached_by_a_forest_track_is_confirmed() -> None:
    """Live: a track entered on the Strada dei Cannoni, in a `__demo` project of its own."""


@scenario(FEATURE, "A 60-item trip with no known roads is on screen within 3 minutes")
def test_a_60_item_trip_with_no_known_roads_is_on_screen_within_3_minutes() -> None:
    """Live: the report of make perf-pi MODE=e2e (10 cold runs)."""

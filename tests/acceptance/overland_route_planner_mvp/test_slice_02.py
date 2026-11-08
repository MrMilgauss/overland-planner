"""pytest-bdd binding: slice 02 scenarios (@pending; enable with --run-pending=slice-02).

Markers per scenario (D199 precedent): the scenarios that run real OR-Tools solves in the solver child, or a browser,
are `solver_child`, so pre-push (`-m "not slow and not solver_child"`) leaves them to CI job 2. The HC-1, HC-5 and A-2
properties solve in-process at layer 1-2 (D192, D215) and stay in pre-push with Hypothesis profile dev; the A-6
property is `@slow` in the feature file (D216). The refusals and settings scenarios never reach a solve.
"""

import pytest
from pytest_bdd import scenario, scenarios

FEATURE = "slice-02-directional-optimizer.feature"


@pytest.mark.solver_child
@scenario(FEATURE, "The Assietta is driven from Pian dell'Alpe to Sestriere even when reversing would be shorter")
def test_the_assietta_is_driven_as_recorded() -> None:
    """Real solve."""


@pytest.mark.solver_child
@scenario(FEATURE, "A loop trail is driven in its recorded order")
def test_a_loop_trail_is_driven_in_its_recorded_order() -> None:
    """Real solve."""


@pytest.mark.solver_child
@scenario(FEATURE, "A plan that would break a hard rule is never shown")
def test_a_plan_that_would_break_a_hard_rule_is_never_shown() -> None:
    """Real solve for the previous successful plan, then waiver W1."""


@pytest.mark.solver_child
@scenario(FEATURE, "Removing the Start POI clears the Start")
def test_removing_the_start_poi_clears_the_start() -> None:
    """Real solve before the removal, so there is a plan to mark Stale (D217)."""


@pytest.mark.solver_child
@scenario(FEATURE, "A trip with only a Start and an End is a direct road route")
def test_a_trip_with_only_a_start_and_an_end() -> None:
    """Real solve."""


@scenario(FEATURE, "Identical inputs produce identical plans")
def test_identical_inputs_produce_identical_plans() -> None:
    """`@solver_child` in the feature file: three real solves and a restart."""


@pytest.mark.solver_child
@scenario(FEATURE, "Totals separate road and off-road driving")
def test_totals_separate_road_and_offroad() -> None:
    """Four real solves on the scripted road map."""


@pytest.mark.solver_child
@scenario(FEATURE, "The itinerary shows each stop with legs and cumulative distance")
def test_the_itinerary_shows_legs_and_cumulative_distance() -> None:
    """Four real solves on the scripted road map."""


@pytest.mark.solver_child
@scenario(FEATURE, "The off-road speed setting changes track durations")
def test_the_offroad_speed_changes_track_durations() -> None:
    """Real solve."""


@pytest.mark.solver_child
@scenario(FEATURE, "Giulia reads the itinerary on her phone")
def test_giulia_reads_the_itinerary_on_her_phone() -> None:
    """Real server, four real solves and a browser."""


scenarios(FEATURE)  # the rest: the properties and the scenarios that never reach a solve

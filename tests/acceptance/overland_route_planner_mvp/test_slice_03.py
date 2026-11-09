"""pytest-bdd binding: slice 03 scenarios (@pending; enable with --run-pending=slice-03).

Markers per scenario (D199 precedent, D221): every scenario that starts a solve child (the real OR-Tools child, or
the scripted child of waiver W1 behind the production parent) or a planner process is `solver_child`, so pre-push
(`-m "not slow and not solver_child"`) leaves it to CI job 2. The scenarios whose text sets a 20 s or 30 s limit wait
for it, and the golden order solves 60 items at the default budget (22 s on the Mac): those four should also be
`slow`, but `slow` is not set here because test_ci_workflow.py pins the slow-properties population (D221); placing
them is the orchestrator's call before slice 03 is enabled. The two
`@pi @requires_external` scenarios are skipped without --run-external and run only through make perf-pi (D96).
The Stop during the road look-up never reaches a solve.
"""

import pytest
from pytest_bdd import scenario, scenarios

FEATURE = "slice-03-pi-performance.feature"


@pytest.mark.solver_child
# slow: recommended, not set (orchestrator decision; tests/ci/test_ci_workflow.py pins the "slow" population)
@scenario(FEATURE, "The best plan found is returned when the optimisation limit is reached")
def test_the_best_plan_is_returned_at_the_optimisation_limit() -> None:
    """W1 scripted child; waits for the 20 s optimisation limit."""


@pytest.mark.solver_child
@scenario(FEATURE, "Marco sees how long planning took")
def test_marco_sees_how_long_planning_took() -> None:
    """Real 60-item solve at the suite's budget."""


@pytest.mark.solver_child
@scenario(FEATURE, "A project above 60 items is planned with a notice that it may take longer")
def test_a_project_above_sixty_items_is_planned_with_a_notice() -> None:
    """Real 65-item solve at the suite's budget."""


# slow: recommended, not set (orchestrator decision; tests/ci/test_ci_workflow.py pins the "slow" population)
@scenario(FEATURE, "The 60-item plan is the same on every machine")
def test_the_sixty_item_plan_is_the_same_on_every_machine() -> None:
    """`@solver_child` in the feature file: a real solve of I1 at the default budget."""


@pytest.mark.solver_child
@scenario(FEATURE, "Marco stops a long optimisation and keeps the best route so far")
def test_marco_stops_and_keeps_the_best_route() -> None:
    """W1 scripted child."""


@pytest.mark.solver_child
@scenario(FEATURE, "Stopping before any valid route fails the run with a reason")
def test_stopping_before_any_valid_route_fails_the_run() -> None:
    """W1 scripted child."""


@pytest.mark.solver_child
# slow: recommended, not set (orchestrator decision; tests/ci/test_ci_workflow.py pins the "slow" population)
@scenario(FEATURE, "No valid route within the feasibility limit")
def test_no_valid_route_within_the_feasibility_limit() -> None:
    """W1 scripted child; waits for the 30 s feasibility limit."""


@pytest.mark.solver_child
@scenario(FEATURE, "The optimizer ends without any route")
def test_the_optimizer_ends_without_any_route() -> None:
    """W1 scripted child."""


@pytest.mark.solver_child
@scenario(FEATURE, "An optimizer that crashes after finding a route still gives the best route so far")
def test_an_optimizer_crash_still_gives_the_best_route() -> None:
    """W1 scripted child, killed with SIGKILL."""


# slow: recommended, not set (orchestrator decision; tests/ci/test_ci_workflow.py pins the "slow" population)
@scenario(FEATURE, "The feasibility limit reached while roads are still being looked up changes nothing")
def test_the_feasibility_limit_during_the_road_look_up() -> None:
    """Waits for the 30 s feasibility limit; never reaches a solve."""


@pytest.mark.solver_child
@scenario(FEATURE, "A later no-change Recalculate returns the same plan as a stopped run")
def test_a_no_change_recalculate_returns_the_stopped_plan() -> None:
    """W1 scripted child."""


@pytest.mark.solver_child
@scenario(FEATURE, "Re-optimise starts a fresh search")
def test_reoptimise_starts_a_fresh_search() -> None:
    """W1 scripted children."""


@scenario(FEATURE, "Closing the planner during a long optimisation leaves nothing running")
def test_closing_the_planner_leaves_nothing_running() -> None:
    """`@solver_child` in the feature file: real planner process and real OR-Tools child."""


@pytest.mark.solver_child
@scenario(FEATURE, "Only one plan is calculated per project at a time")
def test_only_one_plan_per_project_at_a_time() -> None:
    """Real planner process and real OR-Tools child."""


@pytest.mark.solver_child
@scenario(FEATURE, "A plan for a second project waits for the optimizer and can be stopped while waiting")
def test_a_second_project_waits_and_can_be_stopped() -> None:
    """Real planner process and real OR-Tools child."""


@pytest.mark.solver_child
@scenario(FEATURE, "Marco's diagnostics show how planning went")
def test_marcos_diagnostics_show_how_planning_went() -> None:
    """Five real solves of the day trip."""


scenarios(FEATURE)  # the rest: the two @pi scenarios and the Stop during the road look-up

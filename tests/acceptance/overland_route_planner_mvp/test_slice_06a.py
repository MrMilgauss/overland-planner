"""pytest-bdd binding: slice 06a scenarios, bound one step at a time (phase 09). The feature keeps `@slice-06a @pending`
until the last step of the slice, so they run with `--run-pending=slice-06a`.

"A place far from any road" plans four times on the offline road map before it fails at the reachability check; its
first plan is a real solve in the solver child, so pre-push leaves it to CI job 2.
"""

import pytest
from pytest_bdd import scenario

FEATURE = "slice-06a-valhalla-on-the-pi.feature"


@pytest.mark.solver_child
@scenario(FEATURE, "A place far from any road fails the plan and names it")
def test_a_place_far_from_any_road_fails_the_plan_and_names_it() -> None:
    """Off-network place scripted on the offline road map; ends at the reachability check."""

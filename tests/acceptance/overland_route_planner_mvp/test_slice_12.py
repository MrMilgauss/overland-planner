"""pytest-bdd binding: the slice 12 scenarios checked at the HTTP API (US-21: the estimate flag, the GPX names).

The feature is `@slice-12 @pending`: these run only with `--run-pending=slice-12` until the last DELIVER step of the
slice adds it to PENDING_FLAGS in ci.yml. The `@ui` scenarios are checked by tests/e2e/ui-foundation.spec.ts
(Playwright, CI job 7) and are not bound here.

Plan run #4 solves in the solver child, so every scenario is `solver_child` and pre-push leaves them to CI job 2, as for
slices 06a and 09. The Valhalla run plans on the real adapter against the synthetic engine of slice 06a.
"""

import pytest
from pytest_bdd import scenario

FEATURE = "slice-12-ui-foundation.feature"


@pytest.mark.solver_child
@pytest.mark.driving_port
@scenario(FEATURE, "The planner reports a plan on the offline road map as an estimate")
def test_the_planner_reports_a_plan_on_the_offline_road_map_as_an_estimate() -> None:
    """Plan run #4 on the offline road map (`mock:` provider): the run detail says `estimate: true`."""


@pytest.mark.solver_child
@pytest.mark.driving_port
@scenario(FEATURE, "The GPX of an offline-road-map plan says it is an estimate")
def test_the_gpx_of_an_offline_road_map_plan_says_it_is_an_estimate() -> None:
    """Content-Disposition names `...-run4-estimate.gpx`; `<metadata><name>` is "Plan run #4 (estimate)" (D268)."""


@pytest.mark.solver_child
@pytest.mark.driving_port
@scenario(FEATURE, "A plan on real roads is not called an estimate, in the planner or in its GPX")
def test_a_plan_on_real_roads_is_not_called_an_estimate() -> None:
    """Plan run #6 on Valhalla: `estimate: false`, today's file name and trip name."""

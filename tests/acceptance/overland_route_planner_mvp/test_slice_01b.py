"""pytest-bdd binding: slice 01b scenarios (@pending; enable with --run-pending=slice-01b).

D199: `solver_child` keeps every 01b scenario out of pre-push; CI job 2 runs them.
"""

import pytest
from pytest_bdd import scenarios

pytestmark = pytest.mark.solver_child

scenarios("slice-01b-skeleton-plan-and-gpx.feature")

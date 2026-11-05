"""pytest-bdd binding: slice 01b scenarios, blocking in CI job 2 since step 04-11.

D199: the whole module is `solver_child`, not only the first scenario, because most 01b scenarios run real OR-Tools
solves or a browser and would break pre-push's five-minute budget. Pre-push keeps HC-1 through the guard's unit
properties.
"""

import pytest
from pytest_bdd import scenarios

pytestmark = pytest.mark.solver_child

scenarios("slice-01b-skeleton-plan-and-gpx.feature")

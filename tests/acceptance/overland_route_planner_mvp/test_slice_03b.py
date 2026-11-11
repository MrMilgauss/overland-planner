"""pytest-bdd binding: slice 03b scenarios (blocking in CI since step 07-13).

Markers per scenario (D199 precedent): the scenarios that run real OR-Tools solves in the solver child are
`solver_child`, so pre-push (`-m "not slow and not solver_child"`) leaves them to CI job 2. "A trail is never entered
from its exit" ends at the reachability check, before any solve, so it stays in pre-push. The property solves in-process
at layer 1-2 (D192, D215) and keeps Hypothesis profile dev in pre-push. It is `heavy_property` (D221, D226): planning
1,000 sparse projects takes about 9 s at profile ci on the Mac, so it runs in job 10, not job 2;
tests/ci/test_ci_workflow.py pins job 10's population exactly, so the marker and the pin change together (07-13). The
six example scenarios take under 1 s each at profile ci and wait out no limit, so none is `slow`: they block in job 2.
"""

import pytest
from pytest_bdd import scenario

FEATURE = "slice-03b-out-and-back-retrace.feature"


@pytest.mark.solver_child
@scenario(FEATURE, "A dead-end trail is driven in full and then retraced")
def test_a_dead_end_trail_is_driven_in_full_and_then_retraced() -> None:
    """Real solve on the scripted road map."""


@scenario(FEATURE, "A trail is never entered from its exit")
def test_a_trail_is_never_entered_from_its_exit() -> None:
    """Ends at the reachability check: a Failed run, no solve."""


@pytest.mark.solver_child
@scenario(FEATURE, "No retrace when a road leaves the exit")
def test_no_retrace_when_a_road_leaves_the_exit() -> None:
    """Real solve on the scripted road map."""


@pytest.mark.solver_child
@scenario(FEATURE, "A retrace is its own leg and counts as off-road driving")
def test_a_retrace_is_its_own_leg_and_counts_as_offroad() -> None:
    """Real solve on the scripted road map."""


@pytest.mark.solver_child
@scenario(FEATURE, "A dead-end trail just before the End is retraced to reach the End")
def test_a_dead_end_trail_before_the_end_is_retraced() -> None:
    """Real solve on the scripted road map."""


@pytest.mark.solver_child
@scenario(FEATURE, "An order with fewer retraces wins over a shorter order")
def test_an_order_with_fewer_retraces_wins() -> None:
    """Real solve on the scripted road map."""


@pytest.mark.heavy_property  # about 9 s at profile ci on the Mac (07-10, 07-13): job 10 (D221, D226)
@scenario(FEATURE, "No track item is ever driven backwards, retraces included")
def test_no_track_item_is_ever_driven_backwards() -> None:
    """The property, in-process."""

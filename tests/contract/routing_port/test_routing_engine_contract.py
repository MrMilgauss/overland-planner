"""pytest-bdd binding: the routing-port contract suite (DESIGN brief §6, DEVOPS D95; moved here by DISTILL D181).

The same checks run against the recorded Valhalla 3.9.1 answers (respx, CI), the offline road map (MockRoutingProvider)
and, with --run-external, the live Valhalla on the Pi (make contract-live). A scenario loses `@pending` in the step that
turns it green and blocks in CI job 2 at once. Bound so far: the matrix scenarios of the Valhalla adapter (09-02).
Fixtures: tests/contract/fixtures/valhalla-3.9.1/ with its sha256 manifest.
"""

from pathlib import Path

from pytest_bdd import scenario, scenarios

FEATURE = "routing-engine-contract.feature"
FEATURES = {"features_base_dir": Path(__file__).parent}


@scenario(FEATURE, "A Torino to Susa connection is read as one Confirmed leg", **FEATURES)
def test_a_torino_to_susa_connection_is_read_as_one_confirmed_leg() -> None:
    """The adapter reads the recorded 4x4 answer as one Confirmed leg."""


@scenario(FEATURE, "A missing matrix answer confirmed by a route check means no connection at that level", **FEATURES)
def test_a_missing_matrix_answer_confirmed_by_a_route_check_means_no_connection() -> None:
    """The null row of the recorded island matrix is no connection, and nothing else changes."""


@scenario(FEATURE, "A large trip is asked in batches the routing engine accepts", **FEATURES)
def test_a_large_trip_is_asked_in_batches_the_routing_engine_accepts() -> None:
    """3,660 legs are asked in questions of at most 2,500."""


scenarios(FEATURE, **FEATURES)  # the other scenarios stay @pending until their step

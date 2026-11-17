"""pytest-bdd binding: the routing-port contract suite (DESIGN brief §6, DEVOPS D95; moved here by DISTILL D181).

The same checks run against the recorded Valhalla 3.9.1 answers (respx, CI), the offline road map (MockRoutingProvider)
and, with --run-external, the live Valhalla on the Pi (make contract-live). A scenario loses `@pending` in the step that
turns it green and blocks in CI job 2 at once. Bound so far: the matrix scenarios (09-02), the 170 flow,
the version stop and the failures (09-03), the hiccup and the offline road map's parity (09-05),
the live engine (09-11).
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


@scenario(FEATURE, "One place the routing engine cannot snap never removes the other places' legs", **FEATURES)
def test_one_place_the_routing_engine_cannot_snap_never_removes_the_other_places_legs() -> None:
    """Error 170 for a batch: the far place is off the network, the others are answered."""


@scenario(FEATURE, "The contract checks stop when the engine is not the version they were recorded against", **FEATURES)
def test_the_contract_checks_stop_when_the_engine_is_not_the_recorded_version() -> None:
    """The recordings checks stop on another Valhalla version."""


@scenario(FEATURE, "Routing engine failures are reported as failures, never as missing roads", **FEATURES)
def test_routing_engine_failures_are_reported_as_failures_never_as_missing_roads() -> None:
    """Unreachable and unavailable are typed errors, never an answer."""


@scenario(
    FEATURE, "A passing server hiccup is retried and the plan still counts toward the 3-minute promise", **FEATURES
)
def test_a_passing_server_hiccup_is_retried_and_the_plan_still_counts_toward_the_promise() -> None:
    """One 5xx then the recorded answer: one Confirmed leg, and the plan job shows `retried`."""


@scenario(
    FEATURE, "The offline road map reports connections and failures the same way as the routing engine", **FEATURES
)
def test_the_offline_road_map_reports_connections_and_failures_like_the_routing_engine() -> None:
    """The scripted offline road map gives the recorded engine's typed results, check by check."""


@scenario(FEATURE, "The routing engine on the Pi still answers like its recordings", **FEATURES)
def test_the_routing_engine_on_the_pi_still_answers_like_its_recordings() -> None:
    """Layer 2 of make contract-live (D235): the checks through the adapter at `--valhalla-url`; skipped without it."""


scenarios(FEATURE, **FEATURES)  # the other scenarios stay @pending until their step

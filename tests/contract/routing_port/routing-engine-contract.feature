# Routing-port contract suite (DESIGN brief §6, ADR-013, DEVOPS D95; DISTILL D181 moved these here from the
# acceptance features, review B-01). These are @technical checks of the routing boundary: unlike acceptance
# scenarios, their Then steps may assert how the planner questions the routing engine (call shapes), because that
# is the contract (review H-06 exception, D186). Stories: US-10a (slice 06a), US-10b (slice 06b).
# Recorded answers = Valhalla 3.9.1 responses captured by SPIKE-2R (spike/fixtures/index.json names in comments).

@technical @contract @real-io @adapter-integration
Feature: The planner and the routing engine understand each other
  As the planner's maintainer, I want every answer of the routing engine read the same way, whether it comes
  from recorded answers, the offline road map or the live engine on the Pi, so that Marco's legs are never
  mislabelled as missing or as Confirmed.

  @slice-06a @US-10a @J-01
  Scenario: A Torino to Susa connection is read as one Confirmed leg
    # route_torino_susa_4x4v1.json
    Given the routing engine answers with its recorded Torino to Susa route on the 4x4 profile
    When the planner asks for the leg from Torino to Susa
    Then it gets one Confirmed leg with the recorded distance and duration

  @slice-06a @US-10a @J-01 @FR-5.8 @edge
  Scenario: A missing matrix answer confirmed by a route check means no connection at that level
    # matrix_confirmed_with_island_null_row.json + route_442_island_source.json
    Given the routing engine answers with its recorded matrix that has an empty row for an island
    And its recorded route check for that island finds no path
    When the planner asks for the legs from the island
    Then every leg from the island has no connection at the Confirmed level
    And no leg of the other places is affected

  @slice-06a @US-10a @J-01 @error
  Scenario: One place the routing engine cannot snap never removes the other places' legs
    # matrix_170_unsnappable_location_kills_call.json
    Given the routing engine answers with its recorded refusal for a batch that contains one place far from any road
    When the planner asks for that batch of legs
    Then the other places' legs are answered
    And the far place is not recorded as having no connection
    And the planner asked again without that place

  @slice-06a @US-10a @J-01 @edge
  Scenario: A large trip is asked in batches the routing engine accepts
    # matrix_150_pair_limit.json; 60 items + Start and End = 3,660 pairs (D131)
    Given the routing engine accepts at most 2,500 legs per question, as in its recorded refusal
    When the planner asks for the 3,660 legs of the 60-item one-way trip
    Then every leg is answered
    And no single question to the routing engine held more than 2,500 legs

  @slice-06a @US-10a @J-01 @error
  Scenario: The contract checks stop when the engine is not the version they were recorded against
    # status.json (3.9.1)
    Given the routing engine reports version "3.10.0" instead of the recorded "3.9.1"
    When the routing-engine contract checks run against it
    Then they stop with "recorded for Valhalla 3.9.1, found 3.10.0 - re-record the answers"

  @slice-06a @US-10a @J-01 @error @infrastructure-failure
  Scenario Outline: Routing engine failures are reported as failures, never as missing roads
    Given the routing engine <failure>
    When the planner asks for the leg from Torino to Susa
    Then the planner reports the routing engine as <reported>
    And no leg is recorded as having no connection

    Examples:
      | failure                                  | reported    |
      | refuses connections                      | unreachable |
      | does not answer within the time limit    | unreachable |
      | keeps answering with a server error      | unavailable |

  @pending @slice-06a @US-10a @J-01 @K5 @edge
  Scenario: A passing server hiccup is retried and the plan still counts toward the 3-minute promise
    Given the routing engine answers with a server error once and then with its recorded Torino to Susa route
    When the planner asks for the leg from Torino to Susa
    Then it gets one Confirmed leg with the recorded distance and duration
    And the plan is marked as retried, and still counts toward the 3-minute promise

  @pending @slice-06a @US-10a @J-01
  Scenario: The offline road map reports connections and failures the same way as the routing engine
    Given the offline road map scripted with the same connections and failures as the recorded answers
    When the routing-engine contract checks run against the offline road map
    Then every check gives the same result as for the recorded routing engine

  @pending @slice-06a @US-10a @J-01 @requires_external @real_provider @pi
  Scenario: The routing engine on the Pi still answers like its recordings
    Given the planner can reach Valhalla on Marco's Pi through the maintenance tunnel
    When the routing-engine contract checks run against it
    Then every check passes on the live routing engine

  @pending @slice-06b @US-10b @J-01 @FR-5.8 @edge
  Scenario: A place next to a restricted road is classified from both the legal and the permissive look-up
    # locate_permissive_access_restricted_point.json + locate_far_point_empty_edges_cutoff250.json
    Given the routing engine answers with its recorded look-ups for a place 120 m from an access-restricted road and far from any legal road
    When the planner locates that place
    Then the place counts as on the road network for an Unconfirmed leg that ignores access restrictions
    And legal questions to the routing engine never include it

  @pending @slice-06b @US-10b @J-01 @FR-5.8 @error
  Scenario: A permissive retry never snaps a place onto a footpath
    # route_442_permissive_footway_snap_destination.json + route_442_permissive_regression_torino_briancon.json
    Given the routing engine answers with its recorded no-path result when Briancon is sent unsnapped on a permissive question
    When the planner retries a leg to Briancon permissively
    Then the leg is found
    And Briancon was sent at its legally snapped road point

# Slice 06a - plan on the real road network with Valhalla on the Pi. US-10a (J-01) + US-06a S1b.
# Executable SSOT (D140). FR-5.1, FR-5.5, FR-5.8 (Confirmed), NFR-4, NFR-6. DESIGN D40, D44, D50, D128; SPIKE D76.
# The routing-engine contract checks moved to tests/contract/routing_port/ (D181, review B-01).
# Live Valhalla scenarios (@requires_external @real_provider @pi) run through make acceptance-pi / perf-pi, which
# slice 06a-ops (enabler, no scenarios of its own) provides. "Valhalla" is the name Marco sees in his results
# header (policy note L-05), so it is domain language here.

@slice-06a @pending
Feature: Planning on the real road network
  As Marco, I want my plans computed on real roads by the routing engine on my own Pi, with clear messages when it
  is down, so that the km and hours are real and my data stays at home.

  @US-10a @J-01 @requires_external @real_provider @pi
  Scenario: Marco plans with Valhalla on his Pi
    Given the planner routes on Valhalla on Marco's Pi
    When Marco presses Recalculate on "Alpi Occidentali giugno 2027"
    Then the results show "Provider: Valhalla" with the date of its map data and the routing profile "4x4"
    And the Torino to Susa leg is within 15% of the value shown by the openstreetmap.org route planner using its Valhalla engine

  @US-06a @J-01 @K5 @kpi @performance @requires_external @real_provider @pi
  Scenario: A 60-item trip with no known roads is on screen within 3 minutes
    Given the planner routes on Valhalla on Marco's Pi
    And the project of 60 items plus Start and End has no road legs known yet
    And reuse of identical earlier plans is disabled for the measurement
    When Marco presses Recalculate 10 times, the known legs being forgotten before each run
    Then the slowest of the 10 runs took at most 180 seconds from pressing Recalculate to the route on screen
    And every run counts, including retried ones, which are also shown separately

  @US-10a @J-01 @D-7 @FR-5.1 @driving_port
  Scenario: Marco switches the objective to road time
    Given project "Alpi Occidentali giugno 2027" uses the objective "minimise road distance"
    And Marco has selected "minimise road time"
    When he presses Recalculate
    Then the results state the objective "minimise road time"
    And no new road legs were requested

  @US-10a @J-01 @D-7
  Scenario: New projects minimise road distance by default
    Given the planner is running with its default settings
    When Marco creates the project "Dolomiti 2028"
    Then its objective is "minimise road distance"

  @US-10a @J-01 @NFR-6 @G2 @kpi @error @infrastructure-failure
  Scenario: Routing engine unreachable leaves the project intact
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And the routing engine on the Pi cannot be reached
    When Marco presses Recalculate
    Then he sees "Routing engine unreachable - nothing was changed. Try again later."
    And plan run #4 and all items are unchanged

  @US-10a @J-01 @G4 @kpi @error @infrastructure-failure
  Scenario: The routing engine is still loading its map data
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And Valhalla has started but is not ready
    When Marco presses Recalculate
    Then he sees "Routing engine not ready - nothing was changed. Try again shortly."
    And plan run #4 and all items are unchanged
    And the refusal is counted in the diagnostics as a refusal for an engine that was not ready

  @US-10a @J-01 @technical @error @infrastructure-failure
  Scenario: Plans are refused while the routing engine is not the version the planner was checked with
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And the routing engine on the Pi reports version "3.10.0" while the planner expects "3.9.1"
    When Marco presses Recalculate
    Then he sees "Routing engine not ready - nothing was changed. Try again shortly."
    And the health detail names the unexpected routing engine version

  @US-10a @J-01 @NFR-6 @technical @error @infrastructure-failure
  Scenario: Road legs found before the routing engine failed are kept for next time
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And Marco has added POI "Lago del Moncenisio" at 45.2330, 6.9340
    And the routing engine fails after answering 5 of the new legs
    When Marco presses Recalculate
    Then he sees "Routing engine unreachable - nothing was changed. Try again later."
    And the next Recalculate requests only the legs that were not answered

  @US-10a @J-01 @NFR-4 @security
  Scenario Outline: Marco's password is never shown
    Given the shared household password is set in Marco's settings
    And plan run #4 of "Alpi Occidentali giugno 2027" has been exported as GPX
    When Marco looks at <place>
    Then the password does not appear there

    Examples:
      | place                     |
      | the results of plan run #4 |
      | the planner log           |
      | the exported GPX file     |

  @US-10a @J-01 @FR-5.8 @requires_external @real_provider @pi
  Scenario: A trail entry reached by a forest track is Confirmed
    Given the planner routes on Valhalla on Marco's Pi
    And the entry of track "Maira-Varaita ridge" lies on a forest track open to vehicles
    When Marco recalculates
    Then the leg to "Maira-Varaita ridge" is Confirmed

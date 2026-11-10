# Slice 03 - a full-size trip within budget on the Pi, with Stop. US-06a, US-06b (J-01). FR-5.5 (revised), FR-5.6.
# Executable SSOT (D140). "60 items" = 60 Included non-anchor items + Start and End = 62 stops (D131, D146).
# Timing scenarios use waiver W1 (scripted optimizer) where they need a solve that is slow or never valid; the
# 60-item fixture defeats plan reuse. @pi scenarios run only via make perf-pi (slice 03-ops, D96); "the slowest
# of the 10 runs" is the p95 of 10 (D159); every cold run counts, retried ones included (UD-3, D147).
# Slice 03-ops (enabler) supplies the fixtures, the golden order and make perf-pi; it has no scenarios of its own.

@slice-03
Feature: A full-size trip planned within budget, with Stop
  As Marco, I want a 60-item trip planned within minutes on my Pi, and a way to stop early and keep the best
  plan so far, so that a big collection never leaves me waiting with nothing.

  # ===================== US-06a Full-size trip within 3 minutes (J-01, FR-5.5) =====================

  @US-06a @J-01 @K5 @kpi @performance @requires_external @pi
  Scenario: The solve stage for 60 items fits the budget on the Pi
    Given a project of 60 items plus Start and End: 40 tracks and 20 POIs, with Start "Casa Marco, Torino" and End "Briancon"
    And its road distances are already known
    And reuse of identical earlier plans is disabled for the measurement
    When Marco presses Calculate 10 times on his Raspberry Pi
    Then the solve stage of the slowest of the 10 runs took at most 55 seconds

  @US-06a @J-01 @edge
  Scenario: The best plan found is returned when the optimisation limit is reached
    Given the time limits are 10 seconds to find a route and 20 seconds to improve it
    And the search budget would need longer
    When Marco calculates a plan for the 60-item project
    Then a complete plan is shown within 25 seconds
    And it is labelled "not fully optimised (time limit)"

  @US-06a @J-01 @requires_external @pi @performance
  Scenario: A plan found on the Pi is nearly as good as a long search
    Given a reference plan of the 60-item project found with a 30-minute search on a PC
    When Marco calculates a plan for the same project on the Pi with the default search budget
    Then its road km is within 10% of the reference plan

  @US-06a @J-01
  Scenario: Marco sees how long planning took
    Given the 60-item project with its road distances already known
    When Marco calculates a plan for the 60-item project
    Then the results show "Planned 60 items in" followed by the run time

  @US-06a @J-01 @edge
  Scenario: A project above 60 items is planned with a notice that it may take longer
    Given a project of 65 items plus Start and End with its road distances already known
    When Marco presses Calculate
    Then he sees "Large project - calculation may take longer than 3 minutes"
    And the plan is calculated

  @US-06a @J-01 @FR-5.6 @technical @real-io @solver_child
  Scenario: The 60-item plan is the same on every machine
    Given the committed 60-item reference project and its expected order
    When the planner plans it with the default search budget
    Then the order is exactly the expected order

  # ===================== US-06b Stop a long plan early (J-01, FR-5.5) =====================

  @US-06b @J-01 @edge
  Scenario: Marco stops a long optimisation and keeps the best route so far
    Given a plan run of the 60-item project is being optimised and a valid route has been found
    When Marco presses "Stop and use best so far"
    Then the best route found so far is shown
    And it is labelled "not fully optimised (stopped)"

  @US-06b @J-01 @error
  Scenario: Stopping before any valid route fails the run with a reason
    Given a plan run of the 60-item project is being optimised and no valid route has been found yet
    When Marco presses "Stop and use best so far"
    Then the plan run fails with "stopped before a valid route was found"

  @US-06b @J-01 @error
  Scenario: Stopping while roads are still being looked up changes nothing
    Given Marco pressed Recalculate and road legs are still being fetched
    When Marco presses "Stop and use best so far"
    Then no plan run is created
    And he sees "Stopped - nothing was changed"
    And the road legs found so far are kept for the next Recalculate

  @US-06b @J-01 @error
  Scenario: No valid route within the feasibility limit
    Given the feasibility limit is set to 30 seconds and the optimizer finds no valid route for the 60-item project in that time
    When Marco calculates a plan for the 60-item project
    Then he sees "No valid route found within the time limit - plan run #N failed", N being the new run's number

  @US-06b @J-01 @error
  Scenario: The optimizer ends without any route
    Given the optimizer finishes its search for the 60-item project without finding any valid route
    When Marco calculates a plan for the 60-item project
    Then the plan run fails at once with reason "no_valid_route_found"
    And no itinerary is offered

  @US-06b @J-01 @technical @error @infrastructure-failure
  Scenario: An optimizer that crashes after finding a route still gives the best route so far
    Given a plan run of the 60-item project is being optimised and a valid route has been found
    When the optimizer stops abnormally
    Then the best route found so far is shown
    And it is labelled "not fully optimised (optimizer failed)"

  @US-06b @J-01 @technical @error
  Scenario: The feasibility limit reached while roads are still being looked up changes nothing
    Given the feasibility limit is set to 30 seconds and the road look-up for the 60-item project takes longer
    When Marco calculates a plan for the 60-item project
    Then no plan run is created
    And he sees "No valid route found within the time limit - nothing was changed"
    And the road legs found so far are kept for the next Recalculate

  @US-06b @J-01 @A-6
  Scenario: A later no-change Recalculate returns the same plan as a stopped run
    Given a plan run was stopped and labelled "not fully optimised (stopped)"
    When Marco recalculates without changing anything
    Then he sees the identical plan at once, labelled "not fully optimised (stopped)"
    And it says "Reused the identical plan of run" followed by the stopped run's number
    And "Re-optimise (ignore previous result)" is offered

  @US-06b @J-01 @D-73
  Scenario: Re-optimise starts a fresh search
    Given the latest plan run reused a stopped run's plan and offers "Re-optimise (ignore previous result)"
    When Marco chooses "Re-optimise (ignore previous result)"
    Then a fresh search runs and creates a new plan run
    And the new run does not say "Reused the identical plan of run"

  @US-06b @J-01 @technical @error @infrastructure-failure @real-io @adapter-integration @solver_child
  Scenario: Closing the planner during a long optimisation leaves nothing running
    Given a plan run of the 60-item project is being optimised
    When the planner is stopped abruptly
    Then no optimizer process is left running after 3 seconds
    And after the planner starts again no plan run was created for the interrupted plan

  @US-06b @J-01 @technical @error
  Scenario: Only one plan is calculated per project at a time
    Given a plan run of the 60-item project is being optimised
    When Marco presses Recalculate again
    Then he sees "A plan is already being calculated for this project"
    And the running plan continues

  @US-06b @J-01 @technical @edge
  Scenario: A plan for a second project waits for the optimizer and can be stopped while waiting
    Given a plan run of the 60-item project is being optimised
    And Marco pressed Calculate on "Dolomiti 2028", which now waits for the optimizer
    When Marco presses "Stop and use best so far" on "Dolomiti 2028"
    Then no plan run is created for "Dolomiti 2028"
    And the 60-item plan continues

  # ===================== KPI observability (K2, K3, K5, K7) =====================

  @US-06a @J-01 @kpi @K5 @K7 @K2 @K3 @technical @driving_port
  Scenario: Marco's diagnostics show how planning went
    Given Marco planned "Alpi Occidentali giugno 2027" 5 times this evening, each run having its stage timings recorded
    When Marco opens the diagnostics page
    Then he sees the 95th percentile planning time of each stage, counting every run
    And he sees how many runs were retried, shown separately
    And he sees 5 variants tried for that project today
    And he sees 0 plans that broke a hard rule and 0 plans that left an item out of the report

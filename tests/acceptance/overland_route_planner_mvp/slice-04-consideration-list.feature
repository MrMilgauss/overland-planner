# Slice 04 - the consideration list, nothing silently dropped. US-07a (J-03), US-07b (J-05), US-08 (J-05).
# Executable SSOT (D140). HC-3, HC-4 (stale part), A-3, FR-4.1-4.5, FR-6.3, FR-8.2 (revised).
# Tier B (Mandate 10, D114): the plan-iteration journey gets tier_b/test_plan_iteration_state_machine.py when
# DELIVER reaches this slice, reusing these step-methods.

@slice-04 @pending
Feature: Every item accounted for
  As Marco, I want one list where I choose what counts, and a report on every plan that names every item
  as Included, Excluded or Failed, so that nothing I chose is ever silently dropped.

  # ===================== US-07a Choose what counts (J-03) =====================

  @US-07a @J-03 @HC-4 @driving_port
  Scenario: Excluding a trail marks the plan stale without recalculating
    Given plan run #3 of "Alpi Occidentali giugno 2027" is up to date
    When Marco excludes "Via del Sale"
    Then the plan is marked Stale and Recalculate is enabled
    And no new plan run has been created

  @US-07a @J-03 @HC-2 @error
  Scenario: Start and End cannot be excluded
    Given "Casa Marco, Torino" is Start and End
    When Marco looks at the row "Casa Marco, Torino"
    Then it has no Included toggle
    And he sees "Start and End are always included - reassign them instead"

  @US-07a @J-03 @HC-2 @technical @error
  Scenario: Excluding Start or End is refused even when asked directly
    Given "Casa Marco, Torino" is Start and End
    When Marco tries to exclude "Casa Marco, Torino"
    Then he sees "Start and End are always included - reassign them instead"
    And "Casa Marco, Torino" is still Included

  @US-07a @J-03 @driving_port
  Scenario: Marco excludes three tracks at once
    Given "Colle del Sommeiller", "Maira-Varaita ridge" and "Jafferau loop" are selected
    When Marco chooses "Exclude selected"
    Then exactly those 3 tracks are Excluded
    And the plan is marked Stale

  @US-07a @J-03 @driving_port
  Scenario: Marco filters the list to tracks only
    Given project "Alpi Occidentali giugno 2027" has 5 tracks and 7 POIs
    When Marco filters the item list by Tracks
    Then he sees the 5 tracks and no POI

  @US-07a @J-03 @error
  Scenario: Cancelling a removal keeps the item
    Given "Colle del Sommeiller" is in the item list of "Alpi Occidentali giugno 2027"
    When Marco cancels the removal of "Colle del Sommeiller"
    Then "Colle del Sommeiller" is still in the item list

  @US-07a @J-03 @HC-4 @driving_port
  Scenario: Confirming a removal deletes the item and marks the plan stale
    Given "Colle del Sommeiller" is in the item list of "Alpi Occidentali giugno 2027"
    And plan run #4 is up to date
    When Marco confirms the removal of "Colle del Sommeiller"
    Then "Colle del Sommeiller" is no longer in the item list
    And the plan is marked Stale

  # ===================== US-07b Consideration report (J-05, HC-3) =====================

  @US-07b @J-05 @HC-3 @A-3 @K3 @kpi
  Scenario: Every project item is accounted for in the results
    Given project "Alpi Occidentali giugno 2027" has 12 items
    And "Via del Sale" and "Colle del Sommeiller" are Excluded
    When Marco opens plan run #4
    Then the consideration report lists all 12 items
    And 10 are Included with their route position
    And "Via del Sale" and "Colle del Sommeiller" are Excluded

  @US-07b @J-05 @HC-3 @A-3 @K3 @kpi @property
  Scenario: The report is complete for any project
    Given 1000 randomly generated projects with random Included flags
    When a plan is generated for each
    Then each consideration report lists every project item once
    And each status matches the item's Included flag at the time of the run

  @US-07b @J-05 @HC-3 @edge
  Scenario: A past report keeps the selection it was computed with
    Given plan run #4 was computed with "Via del Sale" Excluded
    When Marco includes "Via del Sale" again without recalculating
    Then the report of plan run #4 still shows "Via del Sale" as Excluded
    And the plan is marked Stale

  @US-07b @J-05 @HC-3 @edge
  Scenario: Home in a round trip is listed once
    Given "Casa Marco, Torino" is Start and End of plan run #4
    When Marco opens the consideration report of plan run #4
    Then "Casa Marco, Torino" appears once, Included at positions 1 and 11

  @US-07b @J-05 @HC-3 @FR-5.8 @edge
  Scenario: The report states how far a plan was optimised and how many legs are Unconfirmed
    Given a plan run of "Alpi Occidentali giugno 2027" was stopped after a valid route was found
    And that route uses 2 Unconfirmed legs
    When Marco opens its consideration report
    Then the report header shows "not fully optimised (stopped)"
    And it shows the line "Unconfirmed legs: 2"

  @US-07b @J-05 @HC-3 @error
  Scenario: The report states why a run failed
    Given a plan run of the 60-item project failed because no valid route was found within the feasibility limit
    When Marco opens its consideration report
    Then the report shows the run as Failed with reason "timeout"
    And every item is still listed with its status

  # ===================== US-08 Unreachable item named (J-05, HC-3, FR-8.2) =====================

  @US-08 @J-05 @HC-3 @FR-8.2 @error
  Scenario: An unreachable island fails the run and is named
    Given plan run #5 of "Alpi Occidentali giugno 2027" succeeded
    And Marco has added POI "Isola del Giglio" at 42.3600, 10.9010 as Included
    And no road connects "Isola del Giglio" with any other stop at any confidence level
    When Marco presses Recalculate
    Then plan run #6 fails with "'Isola del Giglio' cannot be connected to any other stop"
    And the report of plan run #6 shows "Isola del Giglio" as Failed with reason "unreachable"

  @US-08 @J-05
  Scenario: Excluding the unreachable item lets the run succeed
    Given plan run #6 failed because of "Isola del Giglio"
    And Marco has excluded "Isola del Giglio"
    When Marco presses Recalculate
    Then plan run #7 succeeds
    And its report shows "Isola del Giglio" as Excluded

  @US-08 @J-05 @HC-3 @error
  Scenario: A failed run never presents a partial plan
    Given plan run #6 failed because of "Isola del Giglio"
    When Marco opens plan run #6
    Then no itinerary and no "Export GPX" are offered for plan run #6
    And plan run #5 is still shown as the latest successful run

  @US-08 @J-05 @FR-8.2 @edge
  Scenario: One missing connection does not fail the plan
    Given plan run #5 of "Alpi Occidentali giugno 2027" has been computed
    And no road connects "Briancon" and "Lago del Moncenisio" directly, but both connect to other stops
    When Marco recalculates
    Then the plan succeeds with an order that avoids that connection

  @US-08 @J-05 @FR-5.8 @edge
  Scenario: Confirmed connections are preferred over a shorter compromise
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And a Confirmed order exists that is 20 km longer than an order using one Unconfirmed leg
    When Marco recalculates
    Then the best order found has no more Unconfirmed legs than the Confirmed order, so it has none

  @US-08 @J-05 @FR-8.2 @error
  Scenario: Every unreachable item is named, not only the first
    Given project "Alpi Occidentali giugno 2027" includes POIs "Isola del Giglio" and "Isola di Capraia"
    And neither island connects with any other stop at any confidence level
    When Marco recalculates
    Then the plan run fails naming both "Isola del Giglio" and "Isola di Capraia"
    And the report shows both as Failed with reason "unreachable"

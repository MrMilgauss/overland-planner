# Slice 10 - see what changed since the last plan run. US-17 (J-03). HC-4 (diff part), FR-6.4, FR-6.6 (view only).
# Executable SSOT (D140). The road deltas of S1 are scripted road-map values, per the DISCUSS timeline.

@slice-10 @pending
Feature: What changed since my last plan
  As Marco, I want to see what each Recalculate changed and to browse past runs,
  so that I can compare variants without copying numbers into a spreadsheet.

  @US-17 @J-03 @HC-4 @FR-6.4 @driving_port
  Scenario: Marco sees what changed after dropping a trail
    Given plan run #3 included "Via del Sale"
    And Marco excluded "Via del Sale" and recalculated into plan run #4
    When he opens the diff of plan run #4 against plan run #3
    Then it shows "Via del Sale" as removed
    And it shows "Briancon" moved from position 5 to position 3
    And it shows road -138.2 km, off-road -38.4 km and total -176.6 km
    And it shows road time -1h38, off-road time -2h34 and total time -4h12
    And it shows "Unconfirmed legs: 0 -> 0"

  @US-17 @J-03 @A-6 @edge
  Scenario: Recalculating without changes shows no changes
    Given plan run #3 of "Dolomiti 2028" is the latest run
    And Marco recalculated without changing anything into plan run #4 of "Dolomiti 2028"
    When he opens the diff of plan run #4 of "Dolomiti 2028" against plan run #3
    Then it shows "No changes"

  @US-17 @J-03 @edge
  Scenario: The first run has nothing to compare with
    Given project "Dolomiti 2028" has just got its first plan run
    When Marco opens the diff of plan run #1 of "Dolomiti 2028"
    Then he sees "No previous run"

  @US-17 @J-03 @HC-3 @edge
  Scenario: A past run keeps its original itinerary
    Given plan run #2 included "Colle del Sommeiller"
    And Marco has since removed "Colle del Sommeiller" from the project
    When he opens plan run #2
    Then plan run #2 still shows "Colle del Sommeiller" in its itinerary

  @US-17 @J-03 @FR-6.6 @driving_port
  Scenario: Marco browses the run history
    Given project "Alpi Occidentali giugno 2027" has plan runs #1 to #4
    When Marco opens the run history
    Then he sees runs #1 to #4, each with time, objective, totals, status (Success / Failed with reason), the "not fully optimised" flag when set, and the number of Unconfirmed legs

  @US-17 @J-03 @error
  Scenario: The history shows a failed run with its reason
    Given plan run #6 of "Alpi Occidentali giugno 2027" failed because of "Isola del Giglio"
    When Marco opens the run history
    Then run #6 is listed as Failed with the reason "'Isola del Giglio' cannot be connected to any other stop"
    And it shows no totals

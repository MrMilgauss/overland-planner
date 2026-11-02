# Slice 05 - Recalculate without re-fetching what is already known. US-09a, US-09b (J-03). HC-4, A-4, FR-7.1-7.5.
# Executable SSOT (D140). A "routing request" = one distinct leg asked of the routing port during a Recalculate
# (DESIGN D24, D130 field names legs_new / legs_cached). Counted by the real CountingRoutingProvider around the
# offline road map. Recorded exception to "Then asserts outcomes, not engine calls" (review H-06, D186): A-4 is
# literally a promise about requests to the routing engine, so these Thens count them.

@slice-05 @pending
Feature: Recalculate reuses what is already known
  As Marco, I want Recalculate to ask the routing engine only for road legs it has never seen,
  so that trying variants on an evening is cheap and quick.

  # ===================== US-09a Recalculate without re-fetching (J-03) =====================

  @US-09a @J-03 @HC-4 @A-4 @K4 @kpi @real-io @adapter-integration
  Scenario: Excluding an item makes zero new routing requests
    Given plan run #3 of "Alpi Occidentali giugno 2027" has been computed
    And Marco has excluded "Via del Sale"
    When he presses Recalculate
    Then the progress shows "computing 0 new legs / 90 cached"
    And no legs were requested from the routing engine
    And the run's log line records 0 new and 90 cached legs

  @US-09a @J-03 @HC-4 @A-4 @K4 @kpi
  Scenario: Adding one POI requests only the legs involving that POI
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And Marco has added POI "Lago del Moncenisio" at 45.2330, 6.9340
    When he presses Recalculate
    Then plan run #5 succeeds
    And every new routing request has "Lago del Moncenisio" at one end
    And the number of new legs shown in the progress equals the number of distinct legs requested from the routing engine

  @US-09a @J-03 @HC-4 @edge
  Scenario: A tiny coordinate correction reuses known legs
    Given "Briancon" was at 44.89900, 6.64300 in plan run #4
    And Marco has corrected it to 44.899001, 6.643002
    When he presses Recalculate
    Then no new legs are requested for "Briancon"

  @US-09a @J-03 @HC-4 @technical @edge
  Scenario: A correction across a rounding step requests only that place's legs again
    Given "Briancon" was at 44.89900, 6.64300 in plan run #4
    And Marco has corrected it to 44.89901, 6.64300
    When he presses Recalculate
    Then every new routing request has "Briancon" at one end

  @US-09a @J-03 @HC-4 @A-4 @edge
  Scenario: Including an item again needs no new legs
    Given plan run #4 of "Alpi Occidentali giugno 2027" was computed with "Via del Sale" Excluded, after run #3 included it
    And Marco has included "Via del Sale" again
    When he presses Recalculate
    Then the progress shows "computing 0 new legs / 110 cached"

  @US-09a @J-03 @HC-4 @edge
  Scenario: Re-importing a removed trail reuses its legs
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And Marco removed "Strada dell'Assietta" and imported "assietta.gpx" again
    When he presses Recalculate
    Then no new legs are requested for "Strada dell'Assietta"

  @US-09a @J-03 @HC-4 @real-io @adapter-integration
  Scenario: Known legs survive a restart
    Given plan run #4 has been computed
    And the planner has been restarted
    When Marco recalculates without changes
    Then the progress shows "computing 0 new legs / 90 cached"

  @US-09a @J-03 @HC-4 @A-4 @K4 @kpi @technical @driving_port
  Scenario: Diagnostics count toggle-only recalculations that needed the routing engine
    Given Marco toggled items and recalculated 3 times this week without adding or moving any place
    When Marco opens the diagnostics page
    Then he sees that 0% of toggle-only recalculations asked the routing engine for legs
    And he sees the share of legs served from the cache

  # ===================== US-09b Make the planner forget known roads (J-03) =====================

  @US-09b @J-03
  Scenario: Switching routing provider recomputes legs from the new provider
    Given plan run #4 was computed on the offline road map
    And the routing provider has been switched to the real provider
    When Marco recalculates
    Then every leg is requested from the real provider
    And no leg of the offline road map is used in the new run

  @US-09b @J-03 @driving_port
  Scenario: Clearing the leg cache of one project recomputes its legs
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And Marco has chosen "Clear leg cache for this project"
    When he presses Recalculate
    Then the progress shows "computing 90 new legs / 0 cached"

  @US-09b @J-03 @driving_port
  Scenario: Clearing the leg cache of all projects recomputes every project
    Given projects "Alpi Occidentali giugno 2027" and "Dolomiti 2028" both have computed plans
    When Marco chooses "Clear leg cache for all projects"
    Then the next Recalculate of each project shows 0 cached legs

  @US-09b @J-03 @edge
  Scenario: Clearing one project's leg cache keeps the other project's legs
    Given projects "Alpi Occidentali giugno 2027" and "Dolomiti 2028" both have computed plans
    When Marco chooses "Clear leg cache for this project" on "Alpi Occidentali giugno 2027"
    Then the next Recalculate of "Dolomiti 2028" shows 0 new legs

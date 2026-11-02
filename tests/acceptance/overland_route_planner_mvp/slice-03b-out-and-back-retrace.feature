# Slice 03b - a dead-end trail is driven and then retraced, never reversed. US-19 (J-02). HC-1, FR-5.8, A-7.
# Executable SSOT (D140). Offline road map with scripted connections per pair. Ordering (UD-4, D148/D125):
# fewest Unconfirmed legs, then fewest retraces, then road km; a retrace penalty is a tie-break only and never
# appears in reported km or time.

@slice-03b @pending
Feature: Dead-end trails are retraced, never reversed
  As Marco, I want a trail whose end leads nowhere to be driven in full and then retraced back to its start,
  never entered from its end, so that dead-end passes like the Sommeiller can still be in my trip.

  @US-19 @J-02 @HC-1 @A-7 @HC-5 @edge
  Scenario: A dead-end trail is driven in full and then retraced
    Given track "Colle del Sommeiller" runs from Rochemolles to Colle del Sommeiller
    And no road leg leaves its exit at Colle del Sommeiller at any confidence level, while one leaves its entry at Rochemolles towards the next stop
    When Marco presses Calculate
    Then the itinerary shows "Colle del Sommeiller  Rochemolles -> Colle del Sommeiller" driven in full
    And the next row is "Retrace Colle del Sommeiller (Colle del Sommeiller -> Rochemolles) - Unconfirmed: retraces the trail backwards; check it is drivable in reverse"
    And the next stop is reached from Rochemolles

  @US-19 @J-02 @HC-1 @FR-8.2 @error
  Scenario: A trail is never entered from its exit
    Given track "Valle Stretta" whose entry cannot be reached at any confidence level but whose exit can
    When Marco presses Calculate
    Then "Valle Stretta" is reported as Failed with reason "unreachable"
    And no plan enters "Valle Stretta" from its exit
    And the plan run is Failed

  @US-19 @J-02 @HC-1 @edge
  Scenario: No retrace when a road leaves the exit
    Given track "Colle del Sommeiller" runs from Rochemolles to Colle del Sommeiller
    And an Unconfirmed road leg leaves its exit towards the next stop
    When Marco presses Calculate
    Then no retrace is planned
    And the plan uses the Unconfirmed road leg from Colle del Sommeiller

  @US-19 @J-02 @FR-5.3
  Scenario: A retrace is its own leg and counts as off-road driving
    Given a plan of "Alpi Occidentali giugno 2027" retraces "Colle del Sommeiller" (12.4 km)
    When Marco opens its results
    Then the retrace is listed as its own leg directly after the track
    And its 12.4 km and duration are included in the off-road totals with no separate breakdown
    And the road and off-road totals hold only distance actually driven

  @US-19 @J-02 @HC-1 @edge
  Scenario: A dead-end trail just before the End is retraced to reach the End
    Given track "Colle del Sommeiller" is the only item between Start "Casa Marco, Torino" and End "Briancon"
    And no road leg leaves its exit at any confidence level, while one leaves its entry towards "Briancon"
    When Marco presses Calculate
    Then the plan drives "Colle del Sommeiller", retraces it, and ends at "Briancon"

  @US-19 @J-02 @HC-1 @FR-5.8 @edge
  Scenario: An order with fewer retraces wins over a shorter order
    Given two dead-end trails can each be reached either with a retrace or by a Confirmed order that is 30 km longer
    When Marco presses Calculate
    Then the plan uses the Confirmed order without any retrace

  @US-19 @J-02 @HC-1 @A-7 @K2 @kpi @property
  Scenario: No track item is ever driven backwards, retraces included
    Given 1000 randomly generated sparse projects with missing road legs at track exits
    When a plan is generated for each
    Then no track item is ever driven from exit to entry
    And every retrace leg follows its own track from exit back to entry directly after that track

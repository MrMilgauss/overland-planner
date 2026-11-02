# Slice 02 - direction-safe optimizer, fixed anchors, honest totals. US-03 (J-02), US-04 (J-01), US-05 (J-03).
# Executable SSOT (D140). HC-1, HC-2, HC-5; A-1, A-2, A-6. Offline road map unless stated.
# @property scenarios run at layer 1-2 (in-memory composition, Hypothesis profile ci = 1,000 cases, dev = 100;
# Mandate 9) with InvariantGuard as the oracle (ADR-009). Pinned readable cases are Hypothesis @example()s in the
# step code, not Gherkin examples (review L-02, D188). The guard scenario uses waiver W1.

@slice-02 @pending
Feature: Direction-safe plans with fixed Start and End
  As Marco, I want every plan to drive each trail whole and the way it was recorded, from my Start to my End,
  and to give the same answer for the same choices, so that I can trust it on the mountain.

  # ===================== US-03 Trails driven as recorded (J-02, HC-1, HC-5) =====================

  @US-03 @J-02 @HC-1 @A-1 @edge
  Scenario: The Assietta is driven from Pian dell'Alpe to Sestriere even when reversing would be shorter
    Given track "Strada dell'Assietta" runs from Pian dell'Alpe (45.0560, 7.0410) to Sestriere (44.9580, 6.8790)
    And Start is "Hotel Sestriere" at 44.9580, 6.8790
    And End is "Rifugio Pian dell'Alpe" at 45.0560, 7.0410
    When Marco presses Calculate
    Then the itinerary row reads "Strada dell'Assietta  Pian dell'Alpe -> Sestriere"
    And the plan has about 43.6 km of road (two legs of about 21.8 km on the offline road map) although a reversed trail would need none

  @US-03 @J-02 @HC-1 @K2 @kpi @property
  Scenario: No generated plan ever drives a track in reverse
    Given 1000 randomly generated projects with 2 to 60 included items
    When a plan is generated for each
    Then every track in every plan is driven from its stored entry to its stored exit

  @US-03 @J-02 @HC-5 @K2 @kpi @property
  Scenario: Tracks are always driven in full
    Given 1000 randomly generated projects with 2 to 60 included items
    When a plan is generated for each
    Then every included track appears exactly once with all its stored points from entry to exit

  @US-03 @J-02 @HC-1 @edge
  Scenario: A loop trail is driven in its recorded order
    Given track "Jafferau loop" from "jafferau-loop.gpx" starts and ends at Bardonecchia
    When Marco presses Calculate
    Then "Jafferau loop" is driven in its stored point order

  @US-03 @J-02 @HC-1 @HC-5 @K2 @kpi @technical @error
  Scenario: A plan that would break a hard rule is never shown
    Given the optimizer proposes an order that drives "Strada dell'Assietta" from Sestriere to Pian dell'Alpe
    When Marco presses Calculate
    Then the plan is not shown and the plan run is marked Failed
    And its consideration report keeps the reason "internal invariant violation"
    And the previous successful plan stays the latest successful run

  # ===================== US-04 Fixed Start and End (J-01, HC-2) =====================

  @US-04 @J-01 @HC-2 @A-2 @K2 @kpi @property
  Scenario: The trip always starts at Start and ends at End
    Given 1000 randomly generated projects with 2 to 60 included items, each with a round trip or a one-way Start and End
    When a plan is generated for each
    Then the first stop of every plan is its Start
    And the last stop of every plan is its End

  @US-04 @J-01 @HC-2 @error
  Scenario Outline: Calculate is refused while an anchor is missing
    Given project "Alpi Occidentali giugno 2027" has no <anchor>
    When Marco presses Calculate
    Then he sees "Set the <anchor> before calculating"
    And no plan run is created

    Examples:
      | anchor |
      | Start  |
      | End    |

  @US-04 @J-01 @D-6
  Scenario: Only POIs can be chosen as Start or End
    Given project "Alpi Occidentali giugno 2027" contains track "Strada dell'Assietta" and POI "Briancon"
    When Marco opens the Start choices
    Then "Briancon" is offered
    And "Strada dell'Assietta" is not offered

  @US-04 @J-01 @D-6 @technical @error
  Scenario: A track cannot be made the Start even when asked directly
    Given project "Alpi Occidentali giugno 2027" contains track "Strada dell'Assietta" and POI "Briancon"
    When Marco tries to set "Strada dell'Assietta" as Start
    Then he sees "Only places (POIs) can be the Start or End"
    And the Start and End are unchanged

  @US-04 @J-01 @HC-2 @error
  Scenario: Removing the Start POI clears the Start
    Given "Casa Marco, Torino" is Start and End
    When Marco confirms the removal of "Casa Marco, Torino" from the project
    Then the project has no Start and no End
    And the plan is marked Stale
    And Calculate is refused with "Set the Start before calculating"

  @US-04 @J-01 @HC-2 @edge
  Scenario: A trip with only a Start and an End is a direct road route
    Given project "Dolomiti 2028" has Start "Cortina d'Ampezzo" and End "Lago di Braies" and nothing else Included
    When Marco presses Calculate
    Then the itinerary is "Cortina d'Ampezzo" then "Lago di Braies" with one road leg
    And the totals show that road leg and no off-road driving

  # ===================== US-05 Repeatable plan with honest totals (J-03, A-6) =====================

  @US-05 @J-03 @A-6 @FR-5.6 @real-io @adapter-integration @solver_child
  Scenario: Identical inputs produce identical plans
    Given plan run #1 of "Dolomiti 2028" has been computed
    And plan run #2 was recalculated without any change
    And the planner was then restarted
    When Marco recalculates without changing anything
    Then plan runs #2 and #3 of "Dolomiti 2028" have the same order, legs and totals as plan run #1

  @US-05 @J-03 @A-6 @FR-5.6 @property
  Scenario: Any project planned twice from scratch gets the same plan
    Given 200 randomly generated projects with 2 to 30 included items
    When each is planned twice with the default search budget and without reusing earlier plans
    Then both plans of every project have the same order, legs and totals

  @US-05 @J-03
  Scenario: Totals separate road and off-road driving
    Given plan run #4 has road legs totalling 612.3 km and 9h40 (scripted road map)
    And it includes tracks "Strada dell'Assietta" 34.2 km, "Jafferau loop" 18.9 km and "Maira-Varaita ridge" 69.5 km
    When Marco opens the results of plan run #4
    Then the totals show road 612.3 km, off-road 122.6 km and total 734.9 km
    And road 9h40, off-road 8h10 and total 17h50

  @US-05 @J-03
  Scenario: The itinerary shows each stop with legs and cumulative distance
    Given in plan run #4 the leg from "Casa Marco, Torino" to the entry of "Strada dell'Assietta" is 86.1 km (scripted road map)
    When Marco opens the itinerary of plan run #4
    Then row 2 shows "Strada dell'Assietta", type Track, leg 86.1 km, cumulative 120.3 km, track 34.2 km and 2h17
    And cumulative distance is road plus off-road km driven up to the end of that stop

  @US-05 @J-03
  Scenario: The off-road speed setting changes track durations
    Given project "Alpi Occidentali giugno 2027" has off-road speed 12 km/h
    When Marco recalculates
    Then "Strada dell'Assietta" shows an off-road duration of 2h51

  @US-05 @J-03 @error @edge
  Scenario Outline: An off-road speed that cannot be driven is refused
    Given project "Alpi Occidentali giugno 2027" has off-road speed 15 km/h
    When Marco sets the off-road speed to <speed> km/h
    Then he sees "Off-road speed must be more than 0 km/h"
    And the off-road speed is still 15 km/h

    Examples:
      | speed |
      | 0     |
      | -5    |

  @US-05 @J-03 @ui @phone
  Scenario: Giulia reads the itinerary on her phone
    Given plan run #4 of "Alpi Occidentali giugno 2027"
    When Giulia opens the results on a 390 px wide phone screen
    Then she can read every stop and the totals without horizontal scrolling

# Slice 09 - see direction on the map and drop POIs by clicking. US-15 (J-02), US-16 (J-01). HC-1 (visual),
# FR-6.5, FR-3.1. Executable SSOT (D140). Map facts are checked through the run's map data (road shapes, styles,
# markers) at the HTTP API; @ui scenarios run in Playwright (tests/e2e/). DESIGN D20, D28, D52.

@slice-09 @pending
Feature: Direction on the map, and POIs by map click
  As Marco, I want the map to show which way every trail is driven and to let me drop places by clicking,
  so that I can see at a glance that no trail runs the wrong way.

  # ===================== US-15 Direction on the map (J-02, HC-1) =====================

  @US-15 @J-02 @HC-1 @FR-6.5 @driving_port
  Scenario: The map shows which way each trail is driven
    Given plan run #4 includes "Strada dell'Assietta"
    When Marco opens the map of plan run #4
    Then "Strada dell'Assietta" is drawn with arrows towards Sestriere and with entry and exit markers
    And road legs are drawn in a different style from tracks
    And stops are numbered 1 to 11 in itinerary order

  @US-15 @J-02 @HC-2 @edge
  Scenario: A round trip shows one combined Start and End marker
    Given "Casa Marco, Torino" is Start and End of plan run #4
    When Marco opens the map of plan run #4
    Then "Casa Marco, Torino" has one combined S/E marker

  @US-15 @J-02 @HC-1
  Scenario: The map follows a reversed track
    Given Marco reversed "Colle del Jafferau descent" and recalculated
    When he opens the map of the new run
    Then its arrows point from Forte Jafferau to Salbertrand

  @US-15 @J-02 @ui @phone
  Scenario: Giulia uses the map on her phone
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    When Giulia opens the map of plan run #4 on her 390 px wide iPhone
    Then she can pan and zoom
    And she can read the stop numbers

  @US-15 @J-02 @error @infrastructure-failure
  Scenario: The map still shows the plan when road shapes are unavailable
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And the road shapes of its legs cannot be fetched from the routing engine
    When Marco opens the map of plan run #4
    Then the road legs are drawn as dashed straight lines marked "geometry unavailable"
    And the tracks are still drawn with their direction arrows

  @US-15 @J-02 @HC-1 @FR-5.8 @edge
  Scenario: Compromise legs stand out on the map
    Given a plan run of "Alpi Occidentali giugno 2027" has an Unconfirmed leg to "Strada dell'Assietta" and a retrace of "Colle del Sommeiller"
    When Marco opens its map
    Then the Unconfirmed leg is drawn in the Unconfirmed style with a "!" badge
    And the retrace is drawn in its own style without direction arrows, labelled "retrace"

  @US-15 @J-02 @FR-6.5 @technical @driving_port
  Scenario: The map uses Marco's chosen map tiles and always credits them
    Given the planner settings choose the OpenTopoMap tiles with their attribution
    When Marco opens any map
    Then the map loads its tiles from OpenTopoMap
    And the attribution "OpenTopoMap" is always shown

  @US-15 @J-02 @NFR-4 @technical @error @security @wiring_e2e @driving_adapter
  Scenario: A map tile address carrying a private access key stops the planner at start-up
    Given the planner settings use a map tile address that carries a private access key
    When Marco starts the planner
    Then the planner refuses to start
    And the planner log names the part that failed and the reason

  @US-15 @US-14 @US-18b @J-02 @ui @driving_adapter
  Scenario: Marco reviews the route with its warnings on the map and exports it
    Given Marco's project "Alpi Occidentali giugno 2027" with its 12 items is open in his desktop browser
    And one trail entry is 1.2 km from the nearest road
    And he has pressed Recalculate and opened the map
    When he presses "Export GPX"
    Then the browser shows the numbered route with arrows on every trail
    And the Warnings section shows the Unconfirmed leg with "check on the ground"
    And a GPX file of the run is downloaded

  # ===================== US-16 Add a POI by map click (J-01) =====================

  @US-16 @J-01 @FR-3.1 @ui
  Scenario: Marco adds a trailhead POI by clicking the map
    Given the map of "Alpi Occidentali giugno 2027" is open in "Click on map" mode
    And Marco has clicked the map at 45.1376, 7.0486
    When he names the POI "Susa trailhead"
    Then POI "Susa trailhead" is added at 45.1376, 7.0486

  @US-16 @J-01 @D-6 @ui
  Scenario: A POI at a trail entry can become the Start
    Given track "Strada dell'Assietta" has its entry at Pian dell'Alpe
    And Marco has added POI "Assietta trailhead" by clicking the entry marker
    When he sets "Assietta trailhead" as Start
    Then "Assietta trailhead" is the Start at the entry coordinates of "Strada dell'Assietta"

  @US-16 @J-01 @error @ui
  Scenario: Cancelling the name prompt adds nothing
    Given the map of "Alpi Occidentali giugno 2027" is open in "Click on map" mode
    And Marco has clicked the map
    When he cancels the name prompt
    Then no POI is added

  @US-16 @US-14 @J-01 @FR-8.3 @edge
  Scenario: A POI clicked next to an existing POI is flagged as a possible duplicate
    Given POI "Briancon" at 44.8990, 6.6430 exists
    And the map of "Alpi Occidentali giugno 2027" is open in "Click on map" mode
    And Marco has clicked the map 30 m from "Briancon"
    When he names the POI "Briancon centro"
    Then a duplicate warning is shown

  @US-16 @J-01 @HC-4
  Scenario: A POI added on the map marks the plan stale
    Given plan run #4 is up to date
    When Marco adds "Susa trailhead" by clicking the map
    Then the plan is marked Stale

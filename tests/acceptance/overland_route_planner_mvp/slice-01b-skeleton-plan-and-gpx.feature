# Slice 01b - first ordered plan and GPX on the tablet. Story US-02b (J-01). HC-1 guard from day 1.
# Executable SSOT (D140); story text in feature-delta.md. Road distances come from the offline road map
# (straight line x 1.3) unless a scenario says otherwise. Action vocabulary: Calculate / Recalculate (D156).
# Steps + scaffolds are written when DELIVER reaches 01b. @technical = outside the UAT band (D141).

@slice-01b @pending
Feature: First ordered plan and GPX
  As Marco, I want my first trail and places put in a sensible order between home and home,
  and handed to my tablet as one GPX file, so that I can drive an Assietta day trip tonight.

  @US-02b @J-01 @HC-2 @driving_port @real-io @adapter-integration @solver_child
  Scenario: Marco gets a first ordered itinerary
    Given project "Alpi Occidentali giugno 2027" has track "Strada dell'Assietta" and POIs "Casa Marco, Torino" and "Briancon"
    And "Casa Marco, Torino" is Start and End
    When Marco presses Calculate
    Then he sees the stops in the order "Casa Marco, Torino", "Strada dell'Assietta", "Briancon", "Casa Marco, Torino"
    And each stop after the first shows its road leg in km

  @US-02b @J-01 @HC-1 @driving_port
  Scenario: Even the first plan drives the trail the way it was recorded
    Given project "Alpi Occidentali giugno 2027" has track "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
    And "Casa Marco, Torino" is Start and End
    And Marco has pressed Calculate
    When Marco exports the plan as GPX
    Then the itinerary shows "Strada dell'Assietta" driven from Pian dell'Alpe to Sestriere
    And the exported file contains its points from Pian dell'Alpe to Sestriere in stored order

  @US-02b @J-01 @A-5 @kpi @K6 @driving_port @real-io @adapter-integration
  Scenario: Marco downloads the first plan as a standard GPX file
    Given plan run #1 of "Alpi Occidentali giugno 2027" exists
    When Marco presses "Export GPX"
    Then he downloads "alpi-occidentali-giugno-2027-run1.gpx"
    And the file is standard GPX 1.1 without proprietary extensions
    And it holds track "Strada dell'Assietta" and the waypoints "Casa Marco, Torino (S/E)" and "Briancon"

  @US-02b @J-01 @A-5 @K6 @kpi @manual
  Scenario: The first plan opens in OsmAnd
    Given Marco downloaded "alpi-occidentali-giugno-2027-run1.gpx"
    When he opens it in OsmAnd on his tablet
    Then OsmAnd shows "Strada dell'Assietta" and the waypoints "Casa Marco, Torino (S/E)" and "Briancon"

  @US-02b @J-01 @HC-2
  Scenario: A one-way trip ends at its End
    Given Start is "Casa Marco, Torino" and End is "Aosta"
    And "Strada dell'Assietta" and "Briancon" are Included
    When Marco presses Calculate
    Then the first stop is "Casa Marco, Torino"
    And the last stop is "Aosta"

  @US-02b @J-01 @HC-1 @edge
  Scenario: A trail that starts at the Start place is reached by a zero-length leg
    Given project "Alpi Occidentali giugno 2027" has track "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
    And "Rifugio Pian dell'Alpe" at the entry of "Strada dell'Assietta" is Start and End
    When Marco presses Calculate
    Then the leg into "Strada dell'Assietta" is 0.0 km
    And the trail is still driven from Pian dell'Alpe to Sestriere

  @US-02b @J-01 @technical @edge
  Scenario: A plan still being worked out cannot be exported yet
    Given Marco pressed Calculate and the plan is still being worked out
    When Marco looks for "Export GPX"
    Then "Export GPX" is not offered until the plan run is ready

  @US-02b @J-01 @technical @error @infrastructure-failure
  Scenario: Plans are refused while the optimizer cannot start
    Given the optimizer could not start when the planner started
    When Marco presses Calculate
    Then he sees "Optimizer unavailable - nothing was changed"
    And no plan run is created
    And the health check reports unhealthy with reason "optimizer_unavailable"

  @US-02b @J-01 @technical @error
  Scenario: A second Calculate while a plan is being worked out is refused
    Given Marco pressed Calculate and the plan is still being worked out
    When he presses Calculate again
    Then he sees "A plan is already being calculated for this project"
    And only one plan run is created

  @US-02b @J-01 @ui @driving_adapter
  Scenario: Marco plans the Assietta day trip in his browser
    Given Marco's project "Alpi Occidentali giugno 2027" is open in his desktop browser with the Assietta, Briancon and home as Start and End
    And he has pressed Calculate
    When he presses "Export GPX"
    Then the browser shows the stops in itinerary order with their road legs
    And a file "alpi-occidentali-giugno-2027-run1.gpx" is downloaded

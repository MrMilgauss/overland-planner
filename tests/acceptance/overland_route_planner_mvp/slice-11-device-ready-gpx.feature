# Slice 11 - load the whole trip into OsmAnd, Locus and Garmin, and know what to trust. US-18a, US-18b (J-04).
# Executable SSOT (D140). A-5, FR-5.8 (GPX marks), FR-6.3, FR-9.1, FR-9.3. ADR-010 + Amendment 1, ADR-009
# Amendment 2, ADR-018. GPX checked against the vendored GPX 1.1 XSD. Device checks are @manual (K6 checklist).
# Every scenario exports in its When step, the manual device checks included; opening the file on a device is
# part of what Marco observes in the Then (review H-05).

@slice-11 @pending
Feature: A device-ready GPX that says what to trust
  As Marco, I want one standard GPX of the whole trip that my devices import cleanly and that marks every
  compromise, so that I can load it in the Defender and know what to check.

  # ===================== US-18a Device-ready GPX (J-04, A-5) =====================

  @US-18a @J-04 @A-5 @FR-9.1 @FR-9.3 @K6 @kpi @driving_port @real-io @adapter-integration
  Scenario: The exported trip is standard GPX with real road shapes
    Given a separate copy of the project as it was at plan run #4, recalculated on the offline road map
    When Marco exports that new plan run as GPX
    Then the file validates against the GPX 1.1 standard without proprietary extensions
    And each road leg follows the road shape returned by the routing engine

  @US-18a @J-04 @A-5 @K6 @kpi @manual
  Scenario: The whole trip opens in OsmAnd in itinerary order
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    When Marco exports plan run #4 as GPX
    Then the file opened in OsmAnd on his tablet shows 7 waypoints, 10 road legs and 3 tracks in itinerary order
    And the home waypoint is named "Casa Marco, Torino (S/E)"

  @US-18a @J-04 @A-5 @D-10
  Scenario: The exported file holds the trip in itinerary order
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    When Marco exports plan run #4 as GPX
    Then the file has 7 waypoints, 10 road legs and 3 tracks in itinerary order
    And the home waypoint is named "Casa Marco, Torino (S/E)"

  @US-18a @J-04 @HC-1 @HC-5
  Scenario: Tracks keep their original detail and direction
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    When Marco exports plan run #4 as GPX
    Then "Strada dell'Assietta" in the file has as many points as "assietta.gpx"
    And it runs from Pian dell'Alpe to Sestriere

  @US-18a @J-04 @manual
  Scenario: Locus Map and Garmin accept the file
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    When Marco exports plan run #4 as GPX
    Then the file loaded into Locus Map and onto his Garmin shows the trip without import errors in both

  @US-18a @J-04 @HC-3 @FR-6.3
  Scenario: The exported file carries the consideration report
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    When Marco exports plan run #4 as GPX
    Then the file includes the consideration report listing all 12 items with their status

  @US-18a @J-04 @K1 @kpi @technical @driving_port
  Scenario: The first export of a big trip records how long planning took
    Given Marco started project "Alpi Occidentali giugno 2027" this evening and it now has 20 items
    When he exports its latest successful plan run as GPX for the first time
    Then the diagnostics page shows the active planning time from the first item to that export

  # ===================== US-18b What the file tells me to trust (J-04) =====================

  @US-18b @J-04 @edge
  Scenario: A stale plan is exported with a clear label
    Given the project changed after plan run #4
    When Marco exports plan run #4 as GPX
    Then the file is labelled "Plan run #4 (stale: project changed since this run)"

  @US-18b @J-04 @error
  Scenario: A failed plan cannot be exported
    Given plan run #6 failed because of "Isola del Giglio"
    When Marco opens plan run #6
    Then "Export GPX" is unavailable with the reason "This plan run failed"

  @US-18b @J-04 @error @infrastructure-failure
  Scenario: Export waits for road shapes
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And the routing engine cannot be reached
    When Marco exports plan run #4 as GPX
    Then he sees "Road shapes could not be fetched from the routing engine - export not possible right now. Try again later."
    And no file is downloaded

  @US-18b @J-04 @FR-5.8 @edge
  Scenario: Unconfirmed legs and retraces are marked in the file
    Given a plan run of "Alpi Occidentali giugno 2027" has an Unconfirmed leg to "Strada dell'Assietta" and a retrace of "Colle del Sommeiller"
    When Marco exports that run as GPX
    Then the Unconfirmed leg's name ends with "[UNCONFIRMED - entry is 1.2 km from the nearest road - check on the ground]"
    And the retrace is written as its own leg whose name is marked UNCONFIRMED
    And the export is not blocked

  @US-18b @J-04 @HC-1 @edge @real-io @adapter-integration
  Scenario: Exporting an older run after a reverse keeps its original direction
    Given plan run #4 drove "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
    And Marco has since reversed "Strada dell'Assietta" without recalculating
    When Marco exports plan run #4 as GPX
    Then the file still drives "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
    And the file is labelled stale

  @US-18b @J-04 @HC-1 @HC-5 @technical @error @infrastructure-failure @real-io @adapter-integration
  Scenario: Track data that no longer matches the run refuses the export
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And the stored points of "Strada dell'Assietta" for that run were damaged on disk
    When Marco exports plan run #4 as GPX
    Then he sees "Track data for this run is inconsistent - recalculate"
    And no file is downloaded

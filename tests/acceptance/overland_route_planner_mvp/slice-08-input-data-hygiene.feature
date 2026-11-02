# Slice 08 - fix backwards and broken input data before it reaches the plan. US-13, US-14 (J-02).
# Executable SSOT (D140). HC-1 (explicit reverse), FR-2.6, FR-2.7, FR-6.7, FR-8.3. ADR-018 (versioned track
# files, crash consistency, job pins D123). "The stored original ... is unchanged" is the FR-2.3 exception (D186).

@slice-08 @pending
Feature: Backwards and broken trail data is fixed or flagged
  As Marco, I want to turn round a trail I recorded backwards on purpose, and to be warned about broken or duplicate
  data, so that bad input never quietly reaches my plan.

  # ===================== US-13 Reverse a backwards recording (J-02, HC-1) =====================

  @US-13 @J-02 @HC-1 @FR-2.7 @driving_port @real-io @adapter-integration
  Scenario: Marco fixes a descent recorded uphill
    Given track "Colle del Jafferau descent" from "jafferau-descent.gpx" runs from Salbertrand to Forte Jafferau
    When Marco confirms "Reverse track direction" with the dialog "will be driven FROM Forte Jafferau TO Salbertrand"
    Then the track runs from Forte Jafferau to Salbertrand
    And project history shows "Reversed Colle del Jafferau descent" with the time
    And the current plan is marked Stale
    And the original "jafferau-descent.gpx" kept by the planner is unchanged

  @US-13 @J-02 @HC-1 @error
  Scenario: Cancelling the reverse dialog changes nothing
    Given track "Colle del Jafferau descent" runs from Salbertrand to Forte Jafferau
    When Marco cancels the "Reverse track direction" dialog
    Then the track still runs from Salbertrand to Forte Jafferau
    And project history has no new entry

  @US-13 @J-02 @HC-1 @edge
  Scenario: Reversing a loop flips its driving direction
    Given track "Jafferau loop" starts and ends at Bardonecchia
    When Marco confirms "Reverse track direction" for it
    Then "Jafferau loop" is driven in the opposite point order
    And it still starts and ends at Bardonecchia

  @US-13 @J-02 @HC-1
  Scenario: Nothing but the explicit action changes a track's direction
    Given track "Strada dell'Assietta" runs from Pian dell'Alpe to Sestriere
    And Marco has renamed it, edited its notes, calculated and recalculated
    When Marco exports the latest plan as GPX
    Then it runs from Pian dell'Alpe to Sestriere in the item list, the itinerary and the exported file

  @US-13 @J-02 @HC-1 @technical @error @infrastructure-failure @real-io @adapter-integration
  Scenario: A reverse interrupted by a crash leaves the trail as it was
    Given track "Colle del Jafferau descent" runs from Salbertrand to Forte Jafferau
    And the planner stopped abruptly after writing the reversed trail but before recording the change
    When the planner starts again
    Then the track still runs from Salbertrand to Forte Jafferau
    And project history has no new entry
    And exporting an earlier plan run gives exactly the same file as before

  @US-13 @J-02 @HC-1 @technical @edge @real-io @adapter-integration
  Scenario: A trail reversed while a plan is being calculated keeps that plan on the old direction
    Given a plan run of "Alpi Occidentali giugno 2027" is being calculated with "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
    When Marco confirms "Reverse track direction" for "Strada dell'Assietta" before the plan finishes
    Then the finished plan drives "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
    And that plan is immediately marked Stale

  # ===================== US-14 Broken data warnings and Results Warnings (J-02) =====================

  @US-14 @J-02 @FR-2.6 @error
  Scenario: A huge jump between points is flagged on import
    Given plan run #7 of "Alpi Occidentali giugno 2027" is the latest run
    And the project does not yet contain "lombarda-glitch.gpx"
    When Marco imports "lombarda-glitch.gpx" with a 14.8 km jump between points 211 and 212
    Then track "Colle della Lombarda" is imported
    And he sees "lombarda-glitch.gpx: jump of 14.8 km between points 211 and 212 - length includes this jump; fix the file and re-import"

  @US-14 @J-02 @FR-2.6 @error @edge
  Scenario: A track with a single point is flagged
    Given project "Alpi Occidentali giugno 2027" is open and does not yet contain "sommeiller-stub.gpx"
    When Marco imports "sommeiller-stub.gpx" which contains 1 point
    Then he sees "sommeiller-stub.gpx contains only 1 point"

  @US-14 @J-02 @FR-8.3 @error
  Scenario: The same file imported twice is flagged as a duplicate
    Given "assietta.gpx" is already in the project
    When Marco imports "assietta.gpx" again
    Then he sees "Possible duplicate of 'Strada dell'Assietta'"
    And the second copy is listed as "Strada dell'Assietta (2)"

  @US-14 @J-02 @FR-8.3 @edge
  Scenario Outline: POIs close to an existing POI are flagged
    Given POI "Briancon" at 44.8990, 6.6430 exists
    When Marco adds POI "Briancon centro" <distance> m away
    Then a duplicate warning is <shown>

    Examples:
      | distance | shown     |
      | 30       | shown     |
      | 80       | not shown |

  @US-14 @J-02 @FR-6.7 @error
  Scenario: The results list unresolved import warnings for the run
    Given Marco imported "lombarda-glitch.gpx" and "assietta.gpx" again after plan run #7
    And "Colle della Lombarda" and "Strada dell'Assietta (2)" are Included with unresolved warnings
    And plan run #8 succeeded
    When Marco opens the results of plan run #8
    Then the Warnings section lists "Colle della Lombarda: jump of 14.8 km between points 211 and 212"
    And it lists "Strada dell'Assietta (2): possible duplicate of 'Strada dell'Assietta'"

  @US-14 @J-02 @FR-6.7
  Scenario: A resolved warning disappears from the next run
    Given plan run #8 lists a duplicate warning for "Strada dell'Assietta (2)"
    And Marco has removed "Strada dell'Assietta (2)"
    When he recalculates
    Then plan run #9 succeeds
    And the Warnings section of plan run #9 no longer lists the duplicate
    And it still lists the jump warning of "Colle della Lombarda"

  @US-14 @J-02 @FR-5.8 @FR-6.7 @edge
  Scenario: The results list Unconfirmed legs under Warnings
    Given a plan run of "Alpi Occidentali giugno 2027" has an Unconfirmed leg from "Briancon" to "Strada dell'Assietta" because its entry is 1.2 km from the nearest road
    And the same run has a retrace of "Colle del Sommeiller"
    When Marco opens the results of that run
    Then the Warnings section lists "Leg 4: Briancon -> Strada dell'Assietta - Unconfirmed: entry is 1.2 km from the nearest road - check on the ground"
    And it lists "Retrace Colle del Sommeiller - Unconfirmed: retraces the trail backwards; check it is drivable in reverse"

  @US-14 @J-02 @FR-2.6 @technical @edge
  Scenario: Sparse forum tracks are not flagged as jumps
    Given Marco's 10-file corpus, whose sparsest track has points up to 2 km apart
    When Marco imports all 10 files
    Then only "lombarda-glitch.gpx" is flagged with a jump

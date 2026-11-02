# Slice 07 - import real, messy GPX collections with trustworthy stats. US-11a, US-11b (J-02), US-12 (J-01).
# Executable SSOT (D140). FR-2.1-2.5, 2.8, 3.2. Needs Marco's real 10-file corpus (D158).
# Recorded exception to "Then asserts outcomes, not storage" (review H-06, D186): FR-2.3 promises the original
# file is kept unmodified, so "The original file is kept unmodified" checks the kept original.

@slice-07 @pending
Feature: Real GPX collections import cleanly
  As Marco, I want to drop my whole download folder of trails at once and get correct stats for each,
  so that I never clean files by hand before planning.

  # ===================== US-11a Import real GPX files with stats (J-02) =====================

  @US-11a @J-02 @driving_port @real-io @adapter-integration
  Scenario: Several files are imported at once with their stats
    Given project "Alpi Occidentali giugno 2027" is open and contains no tracks yet
    When Marco imports "assietta.gpx", "jafferau-loop.gpx" and "maira-varaita.gpx" in one action
    Then he sees 3 tracks, each with name, length, entry and exit, elevation gain and loss, and estimated duration
    And "Strada dell'Assietta" shows 34.2 km, Pian dell'Alpe -> Sestriere, +1210/-850 m, 2h17

  @US-11a @J-02 @error @edge
  Scenario: One bad file among several does not stop the others
    Given project "Alpi Occidentali giugno 2027" is open and contains no tracks yet
    When Marco imports "assietta.gpx", "notes.gpx" and "jafferau-loop.gpx" in one action
    Then he sees tracks "Strada dell'Assietta" and "Jafferau loop"
    And he sees "notes.gpx is not a valid GPX file"
    And nothing from "notes.gpx" is added

  @US-11a @J-02 @edge
  Scenario: A file with two segments becomes two tracks
    Given project "Alpi Occidentali giugno 2027" is open and does not yet contain "via-del-sale.gpx"
    When Marco imports "via-del-sale.gpx" which contains 2 segments
    Then he sees track "Via del Sale seg 1/2" of 22.0 km and track "Via del Sale seg 2/2" of 16.4 km

  @US-11a @J-02 @FR-2.3 @real-io @adapter-integration
  Scenario: The original file is kept unmodified
    Given project "Alpi Occidentali giugno 2027" is open and does not yet contain "assietta.gpx"
    When Marco imports "assietta.gpx"
    Then the original of "assietta.gpx" kept by the planner is byte-identical to the uploaded file

  @US-11a @J-02 @edge
  Scenario: A file without elevation still imports
    Given project "Alpi Occidentali giugno 2027" is open and does not yet contain "maira-varaita.gpx"
    When Marco imports "maira-varaita.gpx" which has no elevation data
    Then track "Maira-Varaita ridge" shows elevation gain and loss as "n/a"

  @US-11a @J-02 @HC-1
  Scenario: Entry and exit are the first and last recorded points
    Given project "Alpi Occidentali giugno 2027" is open and does not yet contain "assietta.gpx"
    When Marco imports "assietta.gpx"
    Then the entry of "Strada dell'Assietta" is the first point of the file
    And its exit is the last point of the file

  @US-11a @J-02 @technical @error @edge @security
  Scenario: More files than the upload limit at once are refused
    Given project "Alpi Occidentali giugno 2027" is open
    When Marco imports 51 GPX files in one action
    Then he sees "At most 50 files can be imported at once"
    And no track is added

  # ===================== US-11b Merge segments and recognise loops (J-02) =====================

  @US-11b @J-02 @driving_port
  Scenario: Two segments of one trail are merged
    Given tracks "Via del Sale seg 1/2" and "Via del Sale seg 2/2" from "via-del-sale.gpx"
    When Marco merges them
    Then he sees one track "Via del Sale" of 38.4 km from Limone Piemonte to Monesi

  @US-11b @J-02 @HC-1 @edge
  Scenario: Merged segments follow the order of the file
    Given tracks "Via del Sale seg 1/2" and "Via del Sale seg 2/2" from "via-del-sale.gpx"
    And Marco has selected "seg 2/2" first and then "seg 1/2"
    When Marco merges them
    Then the merged track "Via del Sale" still runs from Limone Piemonte to Monesi

  @US-11b @J-02 @error
  Scenario: Tracks from different files cannot be merged
    Given tracks "Via del Sale seg 1/2" from "via-del-sale.gpx" and "Strada dell'Assietta" from "assietta.gpx"
    When Marco tries to merge them
    Then he sees "Only segments of the same file can be merged"
    And both tracks are unchanged

  @US-11b @J-02 @HC-1 @edge
  Scenario: A loop trail is labelled and keeps its direction
    Given the loop distance of the project is the default 200 m
    And project "Alpi Occidentali giugno 2027" does not yet contain "jafferau-loop.gpx"
    When Marco imports "jafferau-loop.gpx" whose first and last points are 120 m apart
    Then track "Jafferau loop" is labelled LOOP
    And it keeps its recorded direction

  @US-11b @J-02 @edge
  Scenario: A stricter loop distance changes the label
    Given the loop distance of the project is set to 100 m
    When Marco imports "jafferau-loop.gpx" whose first and last points are 120 m apart
    Then track "Jafferau loop" is not labelled LOOP

  # ===================== US-12 Edit item details (J-01) =====================

  @US-12 @J-01 @FR-4.6
  Scenario: A duration override replaces the estimate in the totals
    Given "Strada dell'Assietta" has an estimated duration of 2h17
    And Marco has set its duration to 3h00
    When he recalculates
    Then the itinerary and totals use 3h00 for "Strada dell'Assietta"

  @US-12 @J-01
  Scenario: A POI visit duration counts in the trip time
    Given POI "Briancon" has a planned visit of 120 minutes
    When Marco recalculates
    Then the total time includes 2h00 at "Briancon"
    And the road time is unchanged

  @US-12 @J-01 @HC-4
  Scenario: Editing details needs no new road legs
    Given plan run #4 of "Alpi Occidentali giugno 2027" is up to date
    And Marco has changed the notes of "Strada dell'Assietta", which marked the plan Stale
    When he recalculates
    Then the progress shows 0 new legs

  @US-12 @J-01 @driving_port
  Scenario: Marco records difficulty and notes for a trail
    Given track "Strada dell'Assietta" has no difficulty and no notes
    When Marco saves difficulty 4 with the note "ford at km 12" on "Strada dell'Assietta"
    Then the item row shows difficulty 4 and the note "ford at km 12"

  @US-12 @J-01 @error @edge
  Scenario Outline: A difficulty outside 1 to 5 is refused
    Given track "Strada dell'Assietta" has difficulty 3
    When Marco sets difficulty <difficulty> on "Strada dell'Assietta"
    Then he sees "Difficulty must be between 1 and 5"
    And "Strada dell'Assietta" still has difficulty 3

    Examples:
      | difficulty |
      | 0          |
      | 6          |

  @US-12 @J-01
  Scenario: Marco categorises a POI
    Given POI "Camping Gran Bosco" has no category
    When Marco sets the category of "Camping Gran Bosco" to "campsite"
    Then "Camping Gran Bosco" shows category "campsite"

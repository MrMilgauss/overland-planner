# Slice 01a - my trail and places on my own Pi. Stories US-01b (J-06), US-02a (J-01), US-02c (J-01).
# Executable SSOT (D140); story text and ACs in feature-delta.md (DISCUSS, Revision 7). US-01a moved to slice 00b.
# Bound to step definitions (steps/catalog_steps.py, steps/platform_steps.py). One scenario at a time: every
# scenario here is @pending until DELIVER enables it; run them all with --run-pending=slice-01a.
# Layer: in-process scenarios = real app + real SQLite/files in a workspace data folder (layer 3, example-only,
# state-delta asserted). @wiring_e2e = real server process. @technical = derived from DESIGN/DEVOPS decisions,
# outside the 3-7 UAT band (D141).

@slice-01a
Feature: My trail and places on my own Pi
  As Marco, I want the planner on my home Pi to keep my projects, trails and places safely,
  so that nothing I enter is lost.

  # ===================== US-01b My trip projects survive restarts (J-06) =====================

  @US-01b @J-06 @driving_port
  Scenario: Marco creates a trip project
    Given the planner is running
    When Marco creates the project "Alpi Occidentali giugno 2027"
    Then he sees an empty workspace titled "Alpi Occidentali giugno 2027"

  @US-01b @J-06 @error
  Scenario Outline: A project without a name is not created
    Given the planner is running
    When Marco creates a project with <name>
    Then he sees "Give the project a name"
    And no project is created

    Examples:
      | name                   |
      | an empty name          |
      | a name of only spaces  |

  @US-01b @J-06 @FR-1.2 @NFR-3 @real-io @adapter-integration
  Scenario: A trip project survives a restart
    Given Marco has created the project "Alpi Occidentali giugno 2027"
    And he has imported "assietta.gpx" into it
    When the planner is restarted
    Then the project "Alpi Occidentali giugno 2027" is still listed
    And it still contains track "Strada dell'Assietta" from Pian dell'Alpe to Sestriere

  @US-01b @J-06 @error @infrastructure-failure
  Scenario: Missing persistent storage is reported instead of losing projects silently
    Given the planner was started on a data folder that would not survive a restart
    When Marco opens the planner home page
    Then he sees "Data directory is not persistent - projects would be lost on restart"
    And the health check reports unhealthy with the same reason

  @US-01b @J-06 @technical @error @infrastructure-failure @requires_external @compose @real-io @adapter-integration
  Scenario: The packaged planner started without its data storage reports that projects would be lost
    Given the packaged planner was started without its data storage
    When Marco asks the planner whether it is healthy
    Then the health check reports unhealthy with "Data directory is not persistent - projects would be lost on restart"

  @US-01b @J-06 @technical @error @infrastructure-failure @wiring_e2e @driving_adapter @real-io @adapter-integration
  Scenario: A data folder the planner cannot write to stops it at start-up
    Given Marco's data folder cannot be written to
    When Marco starts the planner
    Then the planner refuses to start
    And the planner log names the part that failed and the reason

  @US-01b @J-06 @technical @error @infrastructure-failure @wiring_e2e @driving_adapter @real-io @adapter-integration
  Scenario: An older planner refuses data saved by a newer version instead of changing it
    Given Marco's data folder holds the project "Dolomiti 2028" saved by a newer planner version
    When Marco starts the planner
    Then the planner refuses to start
    And the planner log says the data is newer than this planner

  @US-01b @J-06 @technical @error @infrastructure-failure @wiring_e2e @real-io @adapter-integration
  Scenario: Data refused by an older planner is intact when Marco goes back to the newer one
    Given Marco's data folder holds the project "Dolomiti 2028" saved by a newer planner version
    And an older planner has refused to start on it
    When Marco goes back to the newer planner
    Then "Dolomiti 2028" is exactly as he left it

  # ===================== US-02a Load my first trail file (J-01) =====================

  @US-02a @J-01 @HC-1 @real-io @adapter-integration @driving_port
  Scenario: Marco imports his Assietta trail
    Given Marco has created the project "Alpi Occidentali giugno 2027"
    When Marco imports "assietta.gpx"
    Then he sees track "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
    And its length matches the 34.2 km reported by Marco's GPX viewer within 1%

  @US-02a @J-01 @error @real-io @adapter-integration
  Scenario Outline: A file that is not GPX is rejected
    Given Marco has created the project "Alpi Occidentali giugno 2027"
    When Marco imports "<file>" which <content>
    Then he sees "<file> is not a valid GPX file"
    And no track is added

    Examples:
      | file      | content                   |
      | notes.gpx | is a renamed text file    |
      | empty.gpx | is empty                  |

  @US-02a @J-01 @error @edge @real-io @adapter-integration
  Scenario: A trail file without any usable track is rejected
    Given Marco has created the project "Alpi Occidentali giugno 2027"
    When Marco imports "waypoints-only.gpx" which contains places but no track
    Then he sees "waypoints-only.gpx has no usable track"
    And no track is added

  @US-02a @J-01 @technical @error @security @real-io @adapter-integration
  Scenario: A trail file that tries to read other files on the planner is rejected
    Given Marco has created the project "Alpi Occidentali giugno 2027"
    When Marco imports "trap.gpx" which asks the planner to include another file
    Then he sees "trap.gpx is not a valid GPX file"
    And no track is added

  @US-02a @J-01 @technical @error @edge @security
  Scenario: A trail file above the upload limit is refused
    Given Marco has created the project "Alpi Occidentali giugno 2027"
    When Marco imports "huge.gpx" of 26 MB
    Then he sees "huge.gpx is larger than the 25 MB limit"
    And no track is added

  # ===================== US-02c Add my places and set where the trip starts and ends (J-01) =====================

  @US-02c @J-01 @driving_port
  Scenario: Marco adds Briancon by coordinates
    Given Marco has created the project "Alpi Occidentali giugno 2027"
    When Marco adds POI "Briancon" at 44.8990, 6.6430
    Then "Briancon" appears in the item list as an Included POI at 44.8990, 6.6430

  @US-02c @J-01 @error @edge
  Scenario Outline: Coordinates out of range are rejected with a reason
    Given Marco has created the project "Alpi Occidentali giugno 2027"
    When Marco adds POI "Briancon" at <lat>, <lon>
    Then he sees "<reason>"
    And no POI is added

    Examples:
      | lat      | lon       | reason                                 |
      | 144.8990 | 6.6430    | Latitude must be between -90 and 90    |
      | -90.0001 | 6.6430    | Latitude must be between -90 and 90    |
      | 44.8990  | 180.0001  | Longitude must be between -180 and 180 |
      | 44.8990  | -180.5000 | Longitude must be between -180 and 180 |

  @US-02c @J-01 @edge
  Scenario Outline: Coordinates on the edge of the valid range are accepted
    Given Marco has created the project "Alpi Occidentali giugno 2027"
    When Marco adds POI "<name>" at <lat>, <lon>
    Then "<name>" appears in the item list as an Included POI at <lat>, <lon>

    Examples:
      | name        | lat      | lon       |
      | North edge  | 90.0000  | 180.0000  |
      | South edge  | -90.0000 | -180.0000 |

  @US-02c @J-01 @HC-2
  Scenario: Home is both Start and End of a round trip
    Given Marco has created the project "Alpi Occidentali giugno 2027"
    And he has added POI "Casa Marco, Torino" at 45.0703, 7.6869
    When Marco sets "Casa Marco, Torino" as Start and as End
    Then the item list shows one row "Casa Marco, Torino" with an S/E badge

  @US-02c @J-01 @HC-2
  Scenario: A one-way trip has a different Start and End
    Given Marco has created the project "Alpi Occidentali giugno 2027"
    And he has added POI "Casa Marco, Torino" at 45.0703, 7.6869
    And he has added POI "Aosta" at 45.7370, 7.3200
    When Marco sets "Casa Marco, Torino" as Start and "Aosta" as End
    Then "Casa Marco, Torino" shows a Start badge
    And "Aosta" shows an End badge

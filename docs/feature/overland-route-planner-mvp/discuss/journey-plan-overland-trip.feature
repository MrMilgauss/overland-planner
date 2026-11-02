# Journey: Plan an overland trip (docs/product/journeys/plan-overland-trip.yaml)
# Revision 1 (2026-11-01): every story UAT scenario of feature-delta.md is present here, tagged @US-xx.
# Persona: Marco Ferri (overland-planner), Giulia Ferri (household-viewer).
# Revision 2 (current: Revision 6.1): every scenario has an explicit Given; plan-run numbers follow ONE timeline
# (feature-delta.md "[REF] Plan run timeline").
# Reference project "Alpi Occidentali giugno 2027" = 12 items in the project (Included: 12 at #2, 11 at #3, 10 at #4):
#   Tracks (5): Strada dell'Assietta, Jafferau loop, Maira-Varaita ridge, Via del Sale, Colle del Sommeiller
#   POIs (7):   Casa Marco Torino (Start and End), Briancon, Parco Orsiera visitor centre,
#               Camping Gran Bosco, Fuel Oulx, Forte di Fenestrelle, Sacra di San Michele
# Items added LATER in the journey (not part of the 12):
#   before run #5: POI "Lago del Moncenisio" | before run #6: POI "Isola del Giglio"
#   before run #8: track "Colle della Lombarda" (lombarda-glitch.gpx) and duplicate "Strada dell'Assietta (2)"
# Runs: #1 (3 items) ok | #2 (12) ok | #3 Sommeiller Excluded ok | #4 + Via del Sale Excluded ok (reference run)
#       #5 + Lago ok | #6 + Isola FAILED | #7 Isola Excluded ok | #8 + Lombarda + duplicate ok with Warnings
#       #9 duplicate removed ok.  Project "Dolomiti 2028": #1 first run, #2/#3 unchanged recalcs, #4 unchanged recalc.
#   "Dolomiti 2028" is a fixture project: Cortina d'Ampezzo (S/E), Lago di Braies, track Malga Ra Stua, all Included.
# Default project: an unqualified "plan run #N" ALWAYS means "Alpi Occidentali giugno 2027";
#   Dolomiti runs are always written 'plan run #N of "Dolomiti 2028"'.
# Run numbers (Revision 5; full rules in feature-delta.md "[REF] Plan run timeline"):
#   1 Every Optimize/Recalculate that reaches the optimizer creates the next run (unreachable-item failure, Stop before a
#     valid route and feasibility timeout = numbered failed runs). Refused requests (missing anchor, routing engine
#     unreachable/not ready, optimizer unavailable, Stop while legs are fetched) create no run. First Optimize = #1.
#   2 Alpi main line #5-#9 in timeline order (US-09 S2 -> #5, US-08 S1 -> #6, US-08 S2 -> #7, US-14 -> #8, #9).
#   3 Any OTHER scenario that Optimizes/Recalculates is a branch fixture on its own copy; its run number is not asserted.
#   4 A non-recalculating edit followed by opening a run creates no run.
#   5 Fixtures outside the two projects (US-03 S1, US-04, US-06a/b, US-19 S1-S3/S5, property tests) use no run numbers.
# Numbers marked "fixture" are supplied by a stubbed provider; MockProvider numbers are haversine x 1.3.
# "<pi-host>:<port>" = pi.example:8080 by default (DESIGN).
# Revision 6 (post-DESIGN back-propagation, U1-U42): US-06 -> US-06a/US-06b, US-10 -> US-10a/US-10b,
#   US-18 -> US-18a/US-18b, new US-19 (retrace, A-7). The real provider is self-hosted Valhalla on the Pi.
#   Confidence levels (FR-5.8): Confirmed / Unconfirmed (with reason) / None.

Feature: Plan an overland trip
  As Marco, a Defender 90 owner planning an Alpine holiday on his home Pi,
  I want one direction-safe itinerary that visits every trail and place I chose,
  so I can drive trails instead of tarmac and load the trip straight onto my device.

  Background:
    Given the routing provider is the MockProvider with detour factor 1.3

  # ===================== US-01a Planner running on my home Pi (J-06) =====================

  @US-01a @J-06 @walking_skeleton @slice-01a
  Scenario: Marco brings the planner up on his Pi with one command
    Given Marco has copied the compose file and his ".env" to his Raspberry Pi
    When he runs "docker compose up -d"
    Then the planner home page opens at "<pi-host>:<port>" in his desktop browser
    And the health check reports the planner as healthy
    And the start-up is written to the log as one structured line

  @US-01a @J-06 @slice-01a
  Scenario: The same setup runs on Marco's PC
    Given Marco uses the same compose file and ".env" on his amd64 PC
    When he runs "docker compose up -d"
    Then the planner home page opens on the PC

  @US-01a @J-06 @slice-01a
  Scenario: Household members are asked for the shared password when basic auth is enabled
    Given basic auth is enabled in ".env" with user "ferri"
    When Giulia opens the planner from her iPhone without credentials
    Then she is asked to log in
    And no project data is shown

  @US-01a @J-06 @slice-01a
  Scenario: The planner stays on the home network by default
    Given the planner runs with the default configuration
    When Giulia opens "<pi-host>:<port>" from her iPhone on the home Wi-Fi
    Then the planner opens
    And the planner has opened no tunnel and no router port towards the internet

  @US-01a @J-06 @slice-01a
  Scenario: Sharing the planner image never shares Marco's secrets
    Given Marco's ".env" contains his basic-auth password
    When anyone inspects the planner image
    Then the password is not found in it

  @US-01a @J-06 @slice-01a
  Scenario: The idle planner leaves room on the Pi
    Given the planner has been idle for 10 minutes on the Pi
    When Marco checks the planner's memory use, not counting the routing engine
    Then it uses less than 300 MB

  # ===================== US-01b My projects survive restarts (J-06) =====================

  @US-01b @J-06 @walking_skeleton @slice-01a
  Scenario: Marco creates a trip project
    Given the planner is running on Marco's Pi
    When Marco creates the project "Alpi Occidentali giugno 2027"
    Then he sees an empty workspace titled "Alpi Occidentali giugno 2027"

  @US-01b @J-06 @slice-01a
  Scenario: A project without a name is not created
    Given the planner is running on Marco's Pi
    When Marco creates a project with an empty name
    Then he sees "Give the project a name"
    And no project is created

  @US-01b @J-06 @slice-01a
  Scenario: A trip project survives a restart
    Given the project "Alpi Occidentali giugno 2027" exists with track "Strada dell'Assietta"
    When the planner stack is restarted
    Then the project "Alpi Occidentali giugno 2027" is still listed
    And it still contains "Strada dell'Assietta"

  @US-01b @J-06 @slice-01a
  Scenario: Missing persistent storage is reported instead of losing projects silently
    Given the planner was started without a persistent data volume
    When Marco opens the planner home page
    Then he sees "Data directory is not persistent - projects would be lost on restart"
    And the health check reports unhealthy with the same reason

  # ===================== US-02a Load my first trail and places (J-01) =====================

  @US-02a @J-01 @walking_skeleton @slice-01a
  Scenario: Marco imports his Assietta trail
    Given project "Alpi Occidentali giugno 2027" exists
    When Marco imports "assietta.gpx"
    Then he sees track "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
    And its length matches the 34.2 km reported by Marco's GPX viewer within 1%

  @US-02a @J-01 @slice-01a
  Scenario: Marco adds Briancon by coordinates
    Given project "Alpi Occidentali giugno 2027" exists
    When Marco adds POI "Briancon" at 44.8990, 6.6430
    Then "Briancon" appears in the item list as an Included POI at 44.8990, 6.6430

  @US-02a @J-01 @slice-01a
  Scenario: Coordinates out of range are rejected with a reason
    Given project "Alpi Occidentali giugno 2027" exists
    When Marco adds POI "Briancon" at 144.8990, 6.6430
    Then he sees "Latitude must be between -90 and 90"
    And no POI is added

  @US-02a @J-01 @slice-01a
  Scenario: A file that is not GPX is rejected
    Given project "Alpi Occidentali giugno 2027" exists
    When Marco imports "notes.gpx" which is a renamed text file
    Then he sees "notes.gpx is not a valid GPX file"
    And no track is added

  @US-02a @J-01 @walking_skeleton @slice-01a
  Scenario: Home is both Start and End of a round trip
    Given POI "Casa Marco, Torino" at 45.0703, 7.6869 exists
    When Marco sets "Casa Marco, Torino" as Start and as End
    Then the item list shows one row "Casa Marco, Torino" with an S/E badge

  @US-02a @J-01 @slice-01a
  Scenario: A one-way trip has a different Start and End
    Given POIs "Casa Marco, Torino" at 45.0703, 7.6869 and "Aosta" at 45.7370, 7.3200 exist
    When Marco sets "Casa Marco, Torino" as Start and "Aosta" as End
    Then "Casa Marco, Torino" shows a Start badge
    And "Aosta" shows an End badge

  # ===================== US-02b First ordered itinerary and GPX (J-01) =====================

  @US-02b @J-01 @walking_skeleton @slice-01b
  Scenario: Marco gets a first ordered itinerary
    Given project "Alpi Occidentali giugno 2027" has track "Strada dell'Assietta" and POIs "Casa Marco, Torino" and "Briancon"
    And "Casa Marco, Torino" is Start and End
    When Marco presses Optimize
    Then he sees the stops in the order "Casa Marco, Torino", "Strada dell'Assietta", "Briancon", "Casa Marco, Torino"
    And each stop after the first shows its road leg in km

  @US-02b @J-01 @HC-1 @walking_skeleton @slice-01b
  Scenario: Even the first plan drives the trail the way it was recorded
    Given project "Alpi Occidentali giugno 2027" has track "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
    And "Casa Marco, Torino" is Start and End
    When Marco presses Optimize and exports GPX
    Then the itinerary shows "Strada dell'Assietta" driven from Pian dell'Alpe to Sestriere
    And the exported file contains its points from Pian dell'Alpe to Sestriere in stored order

  @US-02b @J-01 @walking_skeleton @slice-01b
  Scenario: Marco downloads the first plan as GPX
    Given plan run #1 of "Alpi Occidentali giugno 2027" exists
    When Marco presses "Export GPX"
    Then he downloads "alpi-occidentali-giugno-2027-run1.gpx"
    And it opens in OsmAnd showing "Strada dell'Assietta" and waypoints "Casa Marco, Torino (S/E)" and "Briancon"

  @US-02b @J-01 @slice-01b
  Scenario: A one-way trip ends at its End
    Given Start is "Casa Marco, Torino" and End is "Aosta"
    And "Strada dell'Assietta" and "Briancon" are Included
    When Marco presses Optimize
    Then the first stop is "Casa Marco, Torino"
    And the last stop is "Aosta"

  # ===================== US-03 Trails driven as recorded (J-02, HC-1, HC-5) =====================

  @US-03 @J-02 @HC-1 @A-1 @slice-02
  Scenario: The Assietta is driven from Pian dell'Alpe to Sestriere even when reversing would be shorter
    Given track "Strada dell'Assietta" runs from Pian dell'Alpe (45.0560, 7.0410) to Sestriere (44.9580, 6.8790)
    And Start is "Hotel Sestriere" at 44.9580, 6.8790
    And End is "Rifugio Pian dell'Alpe" at 45.0560, 7.0410
    When Marco presses Optimize
    Then the itinerary row reads "Strada dell'Assietta  Pian dell'Alpe -> Sestriere"
    And the plan has about 43.6 km of road (two MockProvider legs of about 21.8 km) although a reversed trail would need none

  @US-03 @J-02 @HC-1 @property @slice-02
  Scenario: No generated plan ever drives a track in reverse
    Given 1000 randomly generated projects with 2 to 60 included items
    When a plan is generated for each
    Then every track in every plan is driven from its stored entry to its stored exit

  @US-03 @J-02 @HC-5 @property @slice-02
  Scenario: Tracks are always driven in full
    Given 1000 randomly generated projects with 2 to 60 included items
    When a plan is generated for each
    Then every included track appears exactly once with all its stored points from entry to exit

  @US-03 @J-02 @HC-1 @slice-02
  Scenario: A loop trail is driven in its recorded order
    Given track "Jafferau loop" from "jafferau-loop.gpx" starts and ends at Bardonecchia
    When Marco presses Optimize
    Then "Jafferau loop" is driven in its stored point order

  # ===================== US-04 Fixed Start and End (J-01, HC-2) =====================

  @US-04 @J-01 @HC-2 @A-2 @property @slice-02
  Scenario Outline: The trip always starts at Start and ends at End
    Given a random project of <items> included items generated with seed <seed>
    And Start is "<start>" and End is "<end>"
    When a plan is generated
    Then the first stop is "<start>"
    And the last stop is "<end>"

    Examples:
      | items | seed | start              | end                |
      | 5     | 11   | Casa Marco, Torino | Casa Marco, Torino |
      | 23    | 42   | Casa Marco, Torino | Aosta              |
      | 60    | 7    | Cuneo              | Briancon           |

  @US-04 @J-01 @HC-2 @slice-02
  Scenario Outline: Optimize is refused while an anchor is missing
    Given project "Alpi Occidentali giugno 2027" has no <anchor>
    When Marco presses Optimize
    Then he sees "Set the <anchor> before optimizing"
    And no plan run is created

    Examples:
      | anchor |
      | Start  |
      | End    |

  @US-04 @J-01 @D-6 @slice-02
  Scenario: Only POIs can be chosen as Start or End
    Given project "Alpi Occidentali giugno 2027" contains track "Strada dell'Assietta" and POI "Briancon"
    When Marco opens the Start choices
    Then "Briancon" is offered
    And "Strada dell'Assietta" is not offered

  @US-04 @J-01 @HC-2 @slice-02
  Scenario: Removing the Start POI clears the Start
    Given "Casa Marco, Torino" is Start and End
    When Marco removes "Casa Marco, Torino" from the project and confirms
    Then the project has no Start and no End
    And the plan is marked Stale
    And Optimize is refused with "Set the Start before optimizing"

  # ===================== US-05 Repeatable plan with honest totals (J-03, A-6) =====================

  @US-05 @J-03 @A-6 @property @slice-02
  Scenario: Identical inputs produce identical plans
    Given plan run #1 of "Dolomiti 2028" has been computed
    When Marco recalculates without changing anything, once before and once after a stack restart
    Then plan runs #2 and #3 of "Dolomiti 2028" have the same order, legs and totals as plan run #1

  @US-05 @J-03 @slice-02
  Scenario: Totals separate road and off-road driving
    Given plan run #4 has road legs totalling 612.3 km and 9h40 (fixture)
    And it includes tracks "Strada dell'Assietta" 34.2 km, "Jafferau loop" 18.9 km and "Maira-Varaita ridge" 69.5 km
    When Marco opens the results of plan run #4
    Then the totals show road 612.3 km, off-road 122.6 km and total 734.9 km
    And road 9h40, off-road 8h10 and total 17h50

  @US-05 @J-03 @slice-02
  Scenario: The itinerary shows each stop with legs and cumulative distance
    Given in plan run #4 the leg from "Casa Marco, Torino" to the entry of "Strada dell'Assietta" is 86.1 km (fixture)
    When Marco opens the itinerary of plan run #4
    Then row 2 shows "Strada dell'Assietta", type Track, leg 86.1 km, cumulative 120.3 km, track 34.2 km and 2h17
    And cumulative distance is road plus off-road km driven up to the end of that stop

  @US-05 @J-03 @slice-02
  Scenario: The off-road speed setting changes track durations
    Given project "Alpi Occidentali giugno 2027" has off-road speed 12 km/h
    When Marco recalculates
    Then "Strada dell'Assietta" shows an off-road duration of 2h51

  @US-05 @J-03 @slice-02
  Scenario: Giulia reads the itinerary on her phone
    Given plan run #4 of "Alpi Occidentali giugno 2027"
    When Giulia opens the results on a 390 px wide phone screen
    Then she can read every stop and the totals without horizontal scrolling

  # ===================== US-06a Full-size trip within 3 minutes (J-01, FR-5.5) =====================

  @US-06a @J-01 @performance @slice-03
  Scenario: The solve stage for 60 items fits the budget on the Pi
    Given a project of 60 items: 40 tracks and 20 POIs, of which "Casa Marco, Torino" is Start and "Briancon" is End
    And its road matrix is supplied precomputed in memory
    And reuse of identical earlier plans is disabled for the measurement
    When Marco presses Optimize 10 times on his Raspberry Pi
    Then the 95th percentile of the solve stage is at most 55 seconds

  @US-06a @J-01 @performance @real_provider @slice-06a
  Scenario: A 60-item trip with no known roads is on screen within 3 minutes
    Given the 60-item project with no road legs known yet and Valhalla running on the Pi, overriding the Background
    And reuse of identical earlier plans is disabled for the measurement
    When Marco presses Recalculate 10 times, the known legs being forgotten before each run
    Then the 95th percentile time from pressing Recalculate to the route on screen is at most 180 seconds

  @US-06a @J-01 @slice-03
  Scenario: The best plan found is returned when the optimisation limit is reached
    Given the optimisation limit is set to 20 seconds and the search budget would need longer
    When Marco optimizes the 60-item project
    Then a complete plan is shown within 25 seconds
    And it is labelled "not fully optimised (time limit)"

  @US-06a @J-01 @slice-03
  Scenario: A plan found on the Pi is nearly as good as a long search
    Given a reference plan of the 60-item project found with a 30-minute search on a PC
    When Marco optimizes the same project on the Pi with the default search budget
    Then its road km is within 10% of the reference plan

  @US-06a @J-01 @slice-03
  Scenario: Marco sees how long planning took
    Given the 60-item project with its precomputed road matrix is on Marco's Raspberry Pi
    When Marco optimizes the 60-item project
    Then the results show "Planned 60 items in" followed by the run time

  # ===================== US-06b Stop a long plan early (J-01, FR-5.5) =====================

  @US-06b @J-01 @slice-03
  Scenario: Marco stops a long optimisation and keeps the best route so far
    Given a plan run of the 60-item project is being optimised and a valid route has been found
    When Marco presses "Stop and use best so far"
    Then the best route found so far is shown
    And it is labelled "not fully optimised (stopped)"

  @US-06b @J-01 @slice-03
  Scenario: Stopping before any valid route fails the run with a reason
    Given a plan run of the 60-item project is being optimised and no valid route has been found yet
    When Marco presses "Stop and use best so far"
    Then the plan run fails with "stopped before a valid route was found"

  @US-06b @J-01 @slice-03
  Scenario: Stopping while roads are still being looked up changes nothing
    Given Marco pressed Recalculate and road legs are still being fetched
    When Marco presses "Stop and use best so far"
    Then no plan run is created
    And he sees "Stopped - nothing was changed"

  @US-06b @J-01 @slice-03
  Scenario: No valid route within the feasibility limit
    Given the feasibility limit is set to 30 seconds and the MockProvider delays the search
    When Marco optimizes the 60-item project
    Then the run fails with "No valid route found within the time limit"

  @US-06b @J-01 @A-6 @slice-03
  Scenario: A later no-change Recalculate returns the same plan as a stopped run
    Given a plan run was stopped and labelled "not fully optimised (stopped)"
    When Marco recalculates without changing anything
    Then he sees the identical plan at once, labelled "not fully optimised (stopped)"
    And it says "Reused the identical plan of run" followed by the stopped run's number
    And "Re-optimise (ignore previous result)" is offered

  @US-06b @J-01 @D-73 @slice-03
  Scenario: Re-optimise starts a fresh search
    Given the latest plan run reused a stopped run's plan and offers "Re-optimise (ignore previous result)"
    When Marco chooses "Re-optimise (ignore previous result)"
    Then a fresh search runs and creates a new plan run
    And the new run does not say "Reused the identical plan of run"

  # ===================== US-19 Dead-end trail retraced, never reversed (J-02, HC-1, A-7) =====================

  @US-19 @J-02 @HC-1 @A-7 @slice-03b
  Scenario: A dead-end trail is driven in full and then retraced
    Given track "Colle del Sommeiller" runs from Rochemolles to Colle del Sommeiller
    And no road leg leaves its exit at Colle del Sommeiller at any confidence level, while one leaves its entry at Rochemolles towards the next stop
    When Marco presses Optimize
    Then the itinerary shows "Colle del Sommeiller  Rochemolles -> Colle del Sommeiller" driven in full
    And the next row is "Retrace Colle del Sommeiller (Colle del Sommeiller -> Rochemolles) - Unconfirmed: retraces the trail backwards; check it is drivable in reverse"
    And the next stop is reached from Rochemolles

  @US-19 @J-02 @HC-1 @slice-03b
  Scenario: A trail is never entered from its exit
    Given track "Valle Stretta" whose entry cannot be reached at any confidence level but whose exit can
    When Marco presses Optimize
    Then "Valle Stretta" is reported as Failed with reason "unreachable"
    And no plan enters "Valle Stretta" from its exit
    And the plan run is Failed

  @US-19 @J-02 @HC-1 @slice-03b
  Scenario: No retrace when a road leaves the exit
    Given track "Colle del Sommeiller" runs from Rochemolles to Colle del Sommeiller
    And an Unconfirmed road leg leaves its exit towards the next stop
    When Marco presses Optimize
    Then no retrace is planned
    And the plan uses the Unconfirmed road leg from Colle del Sommeiller

  @US-19 @J-02 @slice-03b
  Scenario: A retrace is its own leg and counts as off-road driving
    Given a plan of "Alpi Occidentali giugno 2027" retraces "Colle del Sommeiller" (12.4 km)
    When Marco opens its results
    Then the retrace is listed as its own leg directly after the track
    And its 12.4 km and duration are included in the off-road totals with no separate breakdown

  @US-19 @J-02 @HC-1 @A-7 @property @slice-03b
  Scenario: No track item is ever driven backwards, retraces included
    Given 1000 randomly generated sparse projects with missing road legs at track exits
    When a plan is generated for each
    Then no track item is ever driven from exit to entry
    And every retrace leg follows its own track from exit back to entry directly after that track

  # ===================== US-07a Choose what counts (J-03) =====================

  @US-07a @J-03 @HC-4 @slice-04
  Scenario: Excluding a trail marks the plan stale without recalculating
    Given plan run #3 of "Alpi Occidentali giugno 2027" is up to date
    When Marco excludes "Via del Sale"
    Then the plan is marked Stale and Recalculate is enabled
    And no new plan run has been created

  @US-07a @J-03 @slice-04
  Scenario: Start and End cannot be excluded
    Given "Casa Marco, Torino" is Start and End
    When Marco looks at the row "Casa Marco, Torino"
    Then it has no Included toggle
    And he sees "Start and End are always included - reassign them instead"

  @US-07a @J-03 @slice-04
  Scenario: Marco excludes three tracks at once
    Given "Colle del Sommeiller", "Maira-Varaita ridge" and "Jafferau loop" are selected
    When Marco chooses "Exclude selected"
    Then exactly those 3 tracks are Excluded
    And the plan is marked Stale

  @US-07a @J-03 @slice-04
  Scenario: Marco filters the list to tracks only
    Given project "Alpi Occidentali giugno 2027" has 5 tracks and 7 POIs
    When Marco filters the item list by Tracks
    Then he sees the 5 tracks and no POI

  @US-07a @J-03 @slice-04
  Scenario: Cancelling a removal keeps the item
    Given "Colle del Sommeiller" is in the item list of "Alpi Occidentali giugno 2027"
    When Marco removes "Colle del Sommeiller" and cancels the confirmation
    Then "Colle del Sommeiller" is still in the item list

  @US-07a @J-03 @slice-04
  Scenario: Confirming a removal deletes the item and marks the plan stale
    Given "Colle del Sommeiller" is in the item list of "Alpi Occidentali giugno 2027"
    And plan run #4 is up to date
    When Marco removes "Colle del Sommeiller" and confirms
    Then "Colle del Sommeiller" is no longer in the item list
    And the plan is marked Stale

  # ===================== US-07b Consideration report (J-05, HC-3) =====================

  @US-07b @J-05 @HC-3 @A-3 @slice-04
  Scenario: Every project item is accounted for in the results
    Given project "Alpi Occidentali giugno 2027" has 12 items
    And "Via del Sale" and "Colle del Sommeiller" are Excluded
    When Marco opens plan run #4
    Then the consideration report lists all 12 items
    And 10 are Included with their route position
    And "Via del Sale" and "Colle del Sommeiller" are Excluded

  @US-07b @J-05 @HC-3 @A-3 @property @slice-04
  Scenario: The report is complete for any project
    Given 1000 randomly generated projects with random Included flags
    When a plan is generated for each
    Then each consideration report lists every project item once
    And each status matches the item's Included flag at the time of the run

  @US-07b @J-05 @HC-3 @slice-04
  Scenario: A past report keeps the selection it was computed with
    Given plan run #4 was computed with "Via del Sale" Excluded
    When Marco includes "Via del Sale" again without recalculating
    Then the report of plan run #4 still shows "Via del Sale" as Excluded
    And the plan is marked Stale

  @US-07b @J-05 @HC-3 @slice-04
  Scenario: Home in a round trip is listed once
    Given "Casa Marco, Torino" is Start and End of plan run #4
    When Marco opens the consideration report of plan run #4
    Then "Casa Marco, Torino" appears once, Included at positions 1 and 11

  @US-07b @J-05 @HC-3 @FR-5.8 @slice-04
  Scenario: The report states how far a plan was optimised and how many legs are Unconfirmed
    Given a plan run of "Alpi Occidentali giugno 2027" was stopped after a valid route was found
    And that route uses 2 Unconfirmed legs
    When Marco opens its consideration report
    Then the report header shows "not fully optimised (stopped)"
    And it shows the line "Unconfirmed legs: 2"

  @US-07b @J-05 @HC-3 @slice-04
  Scenario: The report states why a run failed
    Given a plan run of the 60-item project failed because no valid route was found within the feasibility limit
    When Marco opens its consideration report
    Then the report shows the run as Failed with reason "timeout"
    And every item is still listed with its status

  # ===================== US-08 Unreachable item named (J-05, HC-3, FR-8.2) =====================

  @US-08 @J-05 @HC-3 @slice-04
  Scenario: An unreachable island fails the run and is named
    Given plan run #5 of "Alpi Occidentali giugno 2027" succeeded
    And Marco has added POI "Isola del Giglio" at 42.3600, 10.9010 as Included
    And no road connects "Isola del Giglio" with any other stop at any confidence level
    When Marco presses Recalculate
    Then plan run #6 fails with "'Isola del Giglio' cannot be connected to any other stop"
    And the report of plan run #6 shows "Isola del Giglio" as Failed with reason "unreachable"

  @US-08 @J-05 @slice-04
  Scenario: Excluding the unreachable item lets the run succeed
    Given plan run #6 failed because of "Isola del Giglio"
    When Marco excludes "Isola del Giglio" and presses Recalculate
    Then plan run #7 succeeds
    And its report shows "Isola del Giglio" as Excluded

  @US-08 @J-05 @HC-3 @slice-04
  Scenario: A failed run never presents a partial plan
    Given plan run #6 failed because of "Isola del Giglio"
    When Marco opens plan run #6
    Then no itinerary and no "Export GPX" are offered for plan run #6
    And plan run #5 is still shown as the latest successful run

  @US-08 @J-05 @FR-8.2 @slice-04
  Scenario: One missing connection does not fail the plan
    Given plan run #5 of "Alpi Occidentali giugno 2027" has been computed
    And no road connects "Briancon" and "Lago del Moncenisio" directly, but both connect to other stops
    When Marco recalculates
    Then the plan succeeds with an order that avoids that connection

  @US-08 @J-05 @FR-5.8 @slice-04
  Scenario: Confirmed connections are preferred over a shorter compromise
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And a Confirmed order exists that is 20 km longer than an order using one Unconfirmed leg
    When Marco recalculates
    Then the plan uses the Confirmed order

  # ===================== US-09 Recalculate reuses known legs (J-03, HC-4) =====================

  @US-09 @J-03 @HC-4 @A-4 @slice-05
  Scenario: Excluding an item makes zero new routing requests
    Given plan run #3 of "Alpi Occidentali giugno 2027" has been computed
    And Marco excludes "Via del Sale"
    When he presses Recalculate
    Then the progress shows "computing 0 new legs / 90 cached"
    And no legs were requested from the routing engine
    And the run's log line records 0 new and 90 cached legs

  @US-09 @J-03 @HC-4 @A-4 @slice-05
  Scenario: Adding one POI requests only the legs involving that POI
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And Marco adds POI "Lago del Moncenisio" at 45.2330, 6.9340
    When he presses Recalculate
    Then plan run #5 succeeds
    And every new routing request has "Lago del Moncenisio" at one end
    And the number of new legs shown in the progress equals the number of distinct legs requested from the routing engine

  @US-09 @J-03 @HC-4 @slice-05
  Scenario: A tiny coordinate correction reuses known legs
    Given "Briancon" was at 44.89900, 6.64300 in plan run #4
    When Marco corrects it to 44.899001, 6.643002 and recalculates
    Then no new legs are requested for "Briancon"

  @US-09 @J-03 @slice-05
  Scenario: Switching routing provider recomputes legs from the new provider
    Given plan run #4 was computed with the MockProvider
    When the routing provider is switched to the real provider and Marco recalculates
    Then every leg is requested from the real provider
    And no MockProvider leg is used in the new run

  @US-09 @J-03 @HC-4 @slice-05
  Scenario: Known legs survive a restart
    Given plan run #4 has been computed
    When the planner stack is restarted and Marco recalculates without changes
    Then the progress shows "computing 0 new legs / 90 cached"

  @US-09 @J-03 @slice-05
  Scenario: Clearing the leg cache of one project recomputes its legs
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    When Marco chooses "Clear leg cache for this project" and recalculates
    Then the progress shows "computing 90 new legs / 0 cached"

  @US-09 @J-03 @slice-05
  Scenario: Clearing the leg cache of all projects recomputes every project
    Given projects "Alpi Occidentali giugno 2027" and "Dolomiti 2028" both have computed plans
    When Marco chooses "Clear leg cache for all projects"
    Then the next Recalculate of each project shows 0 cached legs

  # ===================== US-10a Valhalla on the Pi (J-01) =====================

  @US-10a @J-01 @real_provider @slice-06a
  Scenario: Marco plans with Valhalla on his Pi
    Given the routing provider is switched to Valhalla on the Pi, overriding the Background
    When Marco presses Recalculate on "Alpi Occidentali giugno 2027"
    Then the results show "Provider: Valhalla" with the date of its map data and the routing profile "4x4"
    And the Torino to Susa leg is within 15% of the value shown by the openstreetmap.org route planner using its Valhalla engine

  @US-10a @J-01 @D-7 @slice-06a
  Scenario: Marco switches the objective to road time
    Given project "Alpi Occidentali giugno 2027" uses the objective "minimise road distance"
    When Marco selects "minimise road time" and presses Recalculate
    Then the results state the objective "minimise road time"

  @US-10a @J-01 @D-7 @slice-06a
  Scenario: New projects minimise road distance by default
    Given the planner is running with its default settings
    When Marco creates the project "Dolomiti 2028"
    Then its objective is "minimise road distance"

  @US-10a @J-01 @slice-06a
  Scenario: Routing engine unreachable leaves the project intact
    Given the routing engine on the Pi cannot be reached
    When Marco presses Recalculate
    Then he sees "Routing engine unreachable - nothing was changed. Try again later."
    And plan run #4 and all items are unchanged

  @US-10a @J-01 @slice-06a
  Scenario: The routing engine is still loading its map data
    Given Valhalla has started but is not ready
    When Marco presses Recalculate
    Then he sees "Routing engine not ready - nothing was changed. Try again shortly."
    And plan run #4 and all items are unchanged

  @US-10a @J-01 @slice-06a
  Scenario: Marco's password is never shown
    Given Marco's basic-auth password is set in ".env"
    When he views the results, the planner logs and an exported GPX
    Then the password appears in none of them

  @US-10a @J-01 @FR-5.8 @real_provider @slice-06a
  Scenario: A trail entry reached by a forest track is Confirmed
    Given the entry of track "Maira-Varaita ridge" lies on a forest track open to vehicles
    When Marco recalculates with Valhalla
    Then the leg to "Maira-Varaita ridge" is Confirmed

  # ===================== US-10b Compromise legs (J-01, FR-5.8) =====================

  @US-10b @J-01 @FR-5.8 @slice-06b
  Scenario: A leg that needs a compromise is Unconfirmed and explained
    Given the only road to POI "Rifugio Barbara" is tagged no access
    When Marco recalculates
    Then the leg to "Rifugio Barbara" is Unconfirmed with reason "ignores access restrictions"
    And the Warnings list it as "check on the ground"

  @US-10b @J-01 @FR-5.8 @slice-06b
  Scenario: A trail entry near the road gets a short off-network link
    Given the entry of track "Strada dell'Assietta" is 1.2 km from the nearest road and no Confirmed leg reaches it
    When Marco recalculates
    Then the leg to "Strada dell'Assietta" is Unconfirmed with reason "entry is 1.2 km from the nearest road"

  @US-10b @J-01 @FR-5.8 @FR-8.2 @slice-06b
  Scenario: A place too far from any road gets no link
    Given POI "Lago Nero" is 2.1 km from the nearest road and no other leg reaches it
    When Marco recalculates
    Then the run fails with "'Lago Nero' cannot be connected to any other stop"

  # ===================== US-11a Import real GPX files with stats (J-02) =====================

  @US-11a @J-02 @slice-07
  Scenario: Several files are imported at once with their stats
    Given project "Alpi Occidentali giugno 2027" is open and contains no tracks yet
    When Marco imports "assietta.gpx", "jafferau-loop.gpx" and "maira-varaita.gpx" in one action
    Then he sees 3 tracks, each with name, length, entry and exit, elevation gain and loss, and estimated duration
    And "Strada dell'Assietta" shows 34.2 km, Pian dell'Alpe -> Sestriere, +1210/-850 m, 2h17

  @US-11a @J-02 @slice-07
  Scenario: A file with two segments becomes two tracks
    Given project "Alpi Occidentali giugno 2027" is open and does not yet contain "via-del-sale.gpx"
    When Marco imports "via-del-sale.gpx" which contains 2 segments
    Then he sees track "Via del Sale seg 1/2" of 22.0 km and track "Via del Sale seg 2/2" of 16.4 km

  @US-11a @J-02 @slice-07
  Scenario: The original file is kept unmodified
    Given project "Alpi Occidentali giugno 2027" is open and does not yet contain "assietta.gpx"
    When Marco imports "assietta.gpx"
    Then the stored original of "assietta.gpx" is byte-identical to the uploaded file

  @US-11a @J-02 @slice-07
  Scenario: A file without elevation still imports
    Given project "Alpi Occidentali giugno 2027" is open and does not yet contain "maira-varaita.gpx"
    When Marco imports "maira-varaita.gpx" which has no elevation data
    Then track "Maira-Varaita ridge" shows elevation gain and loss as "n/a"

  @US-11a @J-02 @HC-1 @slice-07
  Scenario: Entry and exit are the first and last recorded points
    Given project "Alpi Occidentali giugno 2027" is open and does not yet contain "assietta.gpx"
    When Marco imports "assietta.gpx"
    Then the entry of "Strada dell'Assietta" is the first point of the file
    And its exit is the last point of the file

  # ===================== US-11b Merge segments and recognise loops (J-02) =====================

  @US-11b @J-02 @slice-07
  Scenario: Two segments of one trail are merged
    Given tracks "Via del Sale seg 1/2" and "Via del Sale seg 2/2" from "via-del-sale.gpx"
    When Marco merges them
    Then he sees one track "Via del Sale" of 38.4 km from Limone Piemonte to Monesi

  @US-11b @J-02 @slice-07
  Scenario: Merged segments follow the order of the file
    Given tracks "Via del Sale seg 1/2" and "Via del Sale seg 2/2" from "via-del-sale.gpx"
    When Marco selects "seg 2/2" first, then "seg 1/2", and merges them
    Then the merged track "Via del Sale" still runs from Limone Piemonte to Monesi

  @US-11b @J-02 @slice-07
  Scenario: A loop trail is labelled and keeps its direction
    Given the loop distance of the project is the default 200 m
    And project "Alpi Occidentali giugno 2027" does not yet contain "jafferau-loop.gpx"
    When Marco imports "jafferau-loop.gpx" whose first and last points are 120 m apart
    Then track "Jafferau loop" is labelled LOOP
    And it keeps its recorded direction

  @US-11b @J-02 @slice-07
  Scenario: A stricter loop distance changes the label
    Given the loop distance of the project is set to 100 m
    When Marco imports "jafferau-loop.gpx" whose first and last points are 120 m apart
    Then track "Jafferau loop" is not labelled LOOP

  # ===================== US-12 Edit item details (J-01) =====================

  @US-12 @J-01 @slice-07
  Scenario: A duration override replaces the estimate in the totals
    Given "Strada dell'Assietta" has an estimated duration of 2h17
    When Marco sets its duration to 3h00 and recalculates
    Then the itinerary and totals use 3h00 for "Strada dell'Assietta"

  @US-12 @J-01 @slice-07
  Scenario: A POI visit duration counts in the trip time
    Given POI "Briancon" has a planned visit of 120 minutes
    When Marco recalculates
    Then the total time includes 2h00 at "Briancon"
    And the road time is unchanged

  @US-12 @J-01 @HC-4 @slice-07
  Scenario: Editing details needs no new road legs
    Given plan run #4 of "Alpi Occidentali giugno 2027" is up to date
    When Marco changes the notes of "Strada dell'Assietta" and recalculates
    Then the plan was marked Stale before recalculating
    And the progress shows 0 new legs

  @US-12 @J-01 @slice-07
  Scenario: Marco records difficulty and notes for a trail
    Given track "Strada dell'Assietta" has no difficulty and no notes
    When Marco sets difficulty 4 and the note "ford at km 12" on "Strada dell'Assietta"
    Then the item row shows difficulty 4 and the note "ford at km 12"

  @US-12 @J-01 @slice-07
  Scenario: Marco categorises a POI
    Given POI "Camping Gran Bosco" has no category
    When Marco sets the category of "Camping Gran Bosco" to "campsite"
    Then "Camping Gran Bosco" shows category "campsite"

  # ===================== US-13 Reverse a backwards recording (J-02, HC-1) =====================

  @US-13 @J-02 @HC-1 @slice-08
  Scenario: Marco fixes a descent recorded uphill
    Given track "Colle del Jafferau descent" from "jafferau-descent.gpx" runs from Salbertrand to Forte Jafferau
    When Marco chooses "Reverse track direction" and confirms the dialog "will be driven FROM Forte Jafferau TO Salbertrand"
    Then the track runs from Forte Jafferau to Salbertrand
    And project history shows "Reversed Colle del Jafferau descent" with the time
    And the current plan is marked Stale
    And the stored original "jafferau-descent.gpx" is unchanged

  @US-13 @J-02 @HC-1 @slice-08
  Scenario: Cancelling the reverse dialog changes nothing
    Given track "Colle del Jafferau descent" runs from Salbertrand to Forte Jafferau
    When Marco chooses "Reverse track direction" and cancels
    Then the track still runs from Salbertrand to Forte Jafferau
    And project history has no new entry

  @US-13 @J-02 @HC-1 @slice-08
  Scenario: Reversing a loop flips its driving direction
    Given track "Jafferau loop" starts and ends at Bardonecchia
    When Marco reverses its direction and confirms
    Then "Jafferau loop" is driven in the opposite point order
    And it still starts and ends at Bardonecchia

  @US-13 @J-02 @HC-1 @slice-08
  Scenario: Nothing but the explicit action changes a track's direction
    Given track "Strada dell'Assietta" runs from Pian dell'Alpe to Sestriere
    When Marco renames it, edits its notes, optimizes, recalculates and exports GPX
    Then it runs from Pian dell'Alpe to Sestriere in the item list, the itinerary and the exported file

  # ===================== US-14 Broken data warnings and Results Warnings (J-02) =====================

  @US-14 @J-02 @slice-08
  Scenario: A huge jump between points is flagged on import
    Given plan run #7 of "Alpi Occidentali giugno 2027" is the latest run
    And the project does not yet contain "lombarda-glitch.gpx"
    When Marco imports "lombarda-glitch.gpx" with a 14.8 km jump between points 211 and 212
    Then track "Colle della Lombarda" is imported
    And he sees "lombarda-glitch.gpx: jump of 14.8 km between points 211 and 212 - length includes this jump; fix the file and re-import"

  @US-14 @J-02 @slice-08
  Scenario: A track with a single point is flagged
    Given project "Alpi Occidentali giugno 2027" is open and does not yet contain "sommeiller-stub.gpx"
    When Marco imports "sommeiller-stub.gpx" which contains 1 point
    Then he sees "sommeiller-stub.gpx contains only 1 point"

  @US-14 @J-02 @slice-08
  Scenario: The same file imported twice is flagged as a duplicate
    Given "assietta.gpx" is already in the project
    When Marco imports "assietta.gpx" again
    Then he sees "Possible duplicate of 'Strada dell'Assietta'"
    And the second copy is listed as "Strada dell'Assietta (2)"

  @US-14 @J-02 @slice-08
  Scenario Outline: POIs close to an existing POI are flagged
    Given POI "Briancon" at 44.8990, 6.6430 exists
    When Marco adds POI "Briancon centro" <distance> m away
    Then a duplicate warning is <shown>

    Examples:
      | distance | shown     |
      | 30       | shown     |
      | 80       | not shown |

  @US-14 @J-02 @slice-08
  Scenario: The results list unresolved import warnings for the run
    Given Marco imported "lombarda-glitch.gpx" and "assietta.gpx" again after plan run #7
    And "Colle della Lombarda" and "Strada dell'Assietta (2)" are Included with unresolved warnings
    And plan run #8 succeeded
    When Marco opens the results of plan run #8
    Then the Warnings section lists "Colle della Lombarda: jump of 14.8 km between points 211 and 212"
    And it lists "Strada dell'Assietta (2): possible duplicate of 'Strada dell'Assietta'"

  @US-14 @J-02 @slice-08
  Scenario: A resolved warning disappears from the next run
    Given plan run #8 lists a duplicate warning for "Strada dell'Assietta (2)"
    When Marco removes "Strada dell'Assietta (2)" and recalculates
    Then plan run #9 succeeds
    And the Warnings section of plan run #9 no longer lists the duplicate
    And it still lists the jump warning of "Colle della Lombarda"

  @US-14 @J-02 @FR-5.8 @slice-08
  Scenario: The results list Unconfirmed legs under Warnings
    Given a plan run of "Alpi Occidentali giugno 2027" has an Unconfirmed leg from "Briancon" to "Strada dell'Assietta" because its entry is 1.2 km from the nearest road
    And the same run has a retrace of "Colle del Sommeiller"
    When Marco opens the results of that run
    Then the Warnings section lists "Leg 4: Briancon -> Strada dell'Assietta - Unconfirmed: entry is 1.2 km from the nearest road - check on the ground"
    And it lists "Retrace Colle del Sommeiller - Unconfirmed: retraces the trail backwards; check it is drivable in reverse"

  # ===================== US-15 Direction on the map (J-02, HC-1) =====================

  @US-15 @J-02 @HC-1 @slice-09
  Scenario: The map shows which way each trail is driven
    Given plan run #4 includes "Strada dell'Assietta"
    When Marco opens the map of plan run #4
    Then "Strada dell'Assietta" is drawn with arrows towards Sestriere and with entry and exit markers
    And road legs are drawn in a different style from tracks
    And stops are numbered 1 to 11 in itinerary order

  @US-15 @J-02 @slice-09
  Scenario: A round trip shows one combined Start and End marker
    Given "Casa Marco, Torino" is Start and End of plan run #4
    When Marco opens the map of plan run #4
    Then "Casa Marco, Torino" has one combined S/E marker

  @US-15 @J-02 @HC-1 @slice-09
  Scenario: The map follows a reversed track
    Given Marco reversed "Colle del Jafferau descent" and recalculated
    When he opens the map of the new run
    Then its arrows point from Forte Jafferau to Salbertrand

  @US-15 @J-02 @slice-09
  Scenario: Giulia uses the map on her phone
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    When Giulia opens the map of plan run #4 on her 390 px wide iPhone
    Then she can pan and zoom
    And she can read the stop numbers

  @US-15 @J-02 @slice-09
  Scenario: The map still shows the plan when road shapes are unavailable
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And the road shapes of its legs cannot be fetched from the routing engine
    When Marco opens the map of plan run #4
    Then the road legs are drawn as dashed straight lines marked "geometry unavailable"
    And the tracks are still drawn with their direction arrows

  @US-15 @J-02 @HC-1 @FR-5.8 @slice-09
  Scenario: Compromise legs stand out on the map
    Given a plan run of "Alpi Occidentali giugno 2027" has an Unconfirmed leg to "Strada dell'Assietta" and a retrace of "Colle del Sommeiller"
    When Marco opens its map
    Then the Unconfirmed leg is drawn in the Unconfirmed style with a "!" badge
    And the retrace is drawn in its own style without direction arrows, labelled "retrace"

  # ===================== US-16 Add a POI by map click (J-01) =====================

  @US-16 @J-01 @slice-09
  Scenario: Marco adds a trailhead POI by clicking the map
    Given the map of "Alpi Occidentali giugno 2027" is open in "Click on map" mode
    When Marco clicks the map at 45.1376, 7.0486 and names the POI "Susa trailhead"
    Then POI "Susa trailhead" is added at 45.1376, 7.0486

  @US-16 @J-01 @D-6 @slice-09
  Scenario: A POI at a trail entry can become the Start
    Given track "Strada dell'Assietta" has its entry at Pian dell'Alpe
    When Marco clicks the entry marker, names the POI "Assietta trailhead" and sets it as Start
    Then "Assietta trailhead" is the Start at the entry coordinates of "Strada dell'Assietta"

  @US-16 @J-01 @slice-09
  Scenario: Cancelling the name prompt adds nothing
    Given the map of "Alpi Occidentali giugno 2027" is open in "Click on map" mode
    When Marco clicks the map and cancels the name prompt
    Then no POI is added

  @US-16 @J-01 @slice-09
  Scenario: A POI added on the map marks the plan stale
    Given plan run #4 is up to date
    When Marco adds "Susa trailhead" by clicking the map
    Then the plan is marked Stale

  # ===================== US-17 Diff and history (J-03, HC-4) =====================

  @US-17 @J-03 @HC-4 @slice-10
  Scenario: Marco sees what changed after dropping a trail
    Given plan run #3 included "Via del Sale"
    And Marco excluded "Via del Sale" and recalculated into plan run #4
    When he opens the diff of plan run #4 against plan run #3
    Then it shows "Via del Sale" as removed
    And it shows "Briancon" moved from position 5 to position 3
    And it shows road -138.2 km, off-road -38.4 km and total -176.6 km
    And it shows road time -1h38, off-road time -2h34 and total time -4h12
    And it shows "Unconfirmed legs: 0 -> 0"

  @US-17 @J-03 @A-6 @slice-10
  Scenario: Recalculating without changes shows no changes
    Given plan run #3 of "Dolomiti 2028" is the latest run
    When Marco recalculates without changing anything
    Then the diff of plan run #4 of "Dolomiti 2028" against plan run #3 shows "No changes"

  @US-17 @J-03 @slice-10
  Scenario: The first run has nothing to compare with
    Given project "Dolomiti 2028" has no plan runs
    When Marco optimizes it and opens the diff of plan run #1 of "Dolomiti 2028"
    Then he sees "No previous run"

  @US-17 @J-03 @slice-10
  Scenario: A past run keeps its original itinerary
    Given plan run #2 included "Colle del Sommeiller"
    When Marco removes "Colle del Sommeiller" from the project and opens plan run #2
    Then plan run #2 still shows "Colle del Sommeiller" in its itinerary

  @US-17 @J-03 @slice-10
  Scenario: Marco browses the run history
    Given project "Alpi Occidentali giugno 2027" has plan runs #1 to #4
    When Marco opens the run history
    Then he sees runs #1 to #4, each with time, objective, totals, status (Success / Failed with reason), the "not fully optimised" flag when set, and the number of Unconfirmed legs

  # ===================== US-18a Device-ready GPX (J-04, A-5) =====================

  @US-18a @J-04 @A-5 @slice-11
  Scenario: The exported trip is standard GPX with real road shapes
    Given a plan run of "Alpi Occidentali giugno 2027" computed with Valhalla on its own copy of plan run #4 (branch fixture, rule 3; its number is not asserted)
    When Marco exports GPX
    Then the file validates against the GPX 1.1 schema without proprietary extensions
    And each road leg follows the road shape returned by the routing engine

  @US-18a @J-04 @A-5 @manual @slice-11
  Scenario: The whole trip opens in OsmAnd in itinerary order
    Given Marco exported plan run #4 as GPX
    When he imports the file into OsmAnd
    Then OsmAnd shows 7 waypoints, 10 road legs and 3 tracks in itinerary order
    And the home waypoint is named "Casa Marco, Torino (S/E)"

  @US-18a @J-04 @HC-1 @slice-11
  Scenario: Tracks keep their original detail and direction
    Given Marco exported plan run #4 as GPX
    Then "Strada dell'Assietta" in the file has as many points as "assietta.gpx"
    And it runs from Pian dell'Alpe to Sestriere

  @US-18a @J-04 @manual @slice-11
  Scenario: Locus Map and Garmin accept the file
    Given Marco exported plan run #4 as GPX
    When he imports it into Locus Map and onto his Garmin
    Then both show the trip without import errors

  @US-18a @J-04 @HC-3 @slice-11
  Scenario: The exported file carries the consideration report
    Given Marco exported plan run #4 as GPX
    Then the file includes the consideration report listing all 12 items with their status

  # ===================== US-18b What the file tells me to trust (J-04) =====================

  @US-18b @J-04 @slice-11
  Scenario: A stale plan is exported with a clear label
    Given the project changed after plan run #4
    When Marco exports plan run #4 as GPX
    Then the file is labelled "Plan run #4 (stale: project changed since this run)"

  @US-18b @J-04 @slice-11
  Scenario: A failed plan cannot be exported
    Given plan run #6 failed because of "Isola del Giglio"
    When Marco opens plan run #6
    Then "Export GPX" is unavailable with the reason "This plan run failed"

  @US-18b @J-04 @slice-11
  Scenario: Export waits for road shapes
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    And the routing engine cannot be reached
    When Marco exports plan run #4 as GPX
    Then he sees "Road shapes could not be fetched from the routing engine - export not possible right now. Try again later."
    And no file is downloaded

  @US-18b @J-04 @FR-5.8 @slice-11
  Scenario: Unconfirmed legs and retraces are marked in the file
    Given a plan run of "Alpi Occidentali giugno 2027" has an Unconfirmed leg to "Strada dell'Assietta" and a retrace of "Colle del Sommeiller"
    When Marco exports that run as GPX
    Then the Unconfirmed leg's name ends with "[UNCONFIRMED - entry is 1.2 km from the nearest road - check on the ground]"
    And the retrace is written as its own leg whose name is marked UNCONFIRMED
    And the export is not blocked

  @US-18b @J-04 @HC-1 @slice-11
  Scenario: Exporting an older run after a reverse keeps its original direction
    Given plan run #4 drove "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
    And Marco has since reversed "Strada dell'Assietta" without recalculating
    When Marco exports plan run #4 as GPX
    Then the file still drives "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
    And the file is labelled stale

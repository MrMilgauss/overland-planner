# Slice 12b - the planner follows the trip, not the engine. US-23, US-24, US-25, US-26 (J-01; US-25 also J-04). No new
# planning behaviour, data or endpoint (brief OUT). Executable SSOT (D140). DESIGN D282-D291, DISTILL D292.
#
# Checking tool per scenario:
#  - @driving_port: pytest-bdd (test_slice_12b.py, steps/trip_workflow_steps.py): `GET /api/config/map` names the light
#    base map and its credit beside the unchanged Terrain fields (D287, ADR-004 Amendment 1); a light base map address
#    with a key refuses the start, as the slice 09 tile guard does (real server process, `@wiring_e2e`).
#  - @ui: Playwright, tests/e2e/trip-workflow.spec.ts (one `test.fixme` per scenario, one per outline row, until
#    DELIVER), on chromium (desktop; 1440 x 900 set per test) and webkit-iphone14 (390 px), CI job 7 against the
#    packaged planner (offline road map). Data is seeded as slice 12 does: the page itself (New project, Add, the row
#    menu, Plan the route) and `page.request` to the planner's own API. States the packaged planner cannot reach on its
#    own (Loading, Planning, Couldn't plan, a Valhalla run, a retrace, a stopped plan, the large-project notice, an
#    unanswering engine) are set by rewriting the planner's answer in the browser (policy waiver W4, as D275): the real
#    answer is read once with `page.request` at setup and the route handler only fulfills it. The base map never comes
#    from the internet: the light base map's style address is answered with a small style of the test's own and every
#    other foreign request with a blank tile (tests/e2e/blankTile.ts).
#    Inner checks of DESIGN (vitest + jsdom: tripPhase, planState, PlanPanel, RouteCard, RunDetails, Itinerary,
#    TripList, AddMenu, TripMap, runMap; pytest: settings and /api/config/map) come with each scenario in DELIVER.
# Run numbers, item counts and timings below are the owner's trip (the domain example). The browser checks read the
# planner's own lines from its answer and check where they are shown, word for word (D211); they do not re-create
# run #7 by seven presses. The GPX file names are the planner's, unchanged since slice 12 (D268).

@slice-12b @pending
Feature: The planner follows the trip
  As Marco and Giulia, we want the page to walk us through our trip in three phases (build it, plan it, see the route),
  so that we always know what to press next, read the route as the main result and never mistake an engine detail,
  an older route or an estimate for the route we are about to drive.

  # ===================== US-23 Build the trip, plan it, see the route (J-01) =====================

  # trip-workflow.spec.ts: "A project without a route opens on Build the trip" (chromium and webkit-iphone14; real: a new
  # project with the Assietta trail and a place). Inner: tripPhase.test.ts, WorkspacePage.test.ts.
  @US-23 @J-01 @ui
  Scenario: A project without a route opens on Build the trip
    Given "Assietta weekend" has the trail "Strada dell'Assietta" and the place "Torino" and has no route yet
    When Marco opens the project
    Then the page shows the phase "Build the trip" with one list holding "Strada dell'Assietta" and "Torino"
    And the status reads "No plan yet"
    And the only main action is "Plan the route"
    And no summary card, itinerary, "Export GPX" or "Details" is shown

  # trip-workflow.spec.ts: "Every way to add a stop is in one Add control and lands in the one list" (chromium; real).
  # Inner: AddMenu.test.ts, TripMap (items mode, D288).
  @US-23 @J-01 @ui
  Scenario: Every way to add a stop is in one Add control and lands in the one list
    Given Marco is building "Assietta weekend"
    When he opens "Add"
    Then he can upload a GPX file, click on the map, or type coordinates
    And after he types "Lago del Moncenisio" at 45.2280, 6.9420 the place is in the same list as "Strada dell'Assietta"

  # trip-workflow.spec.ts: "Start and End are set on a place in the list" (chromium; real: the anchors call).
  # Inner: TripList.test.ts (row menu, "not saved yet" until both are chosen).
  @US-23 @J-01 @ui
  Scenario: Start and End are set on a place in the list
    Given the list of "Assietta weekend" holds the place "Torino" and the trail "Strada dell'Assietta"
    When Marco makes "Torino" the Start and the End from its row
    Then the row of "Torino" says it is the Start and the End
    And the row of "Strada dell'Assietta" offers no Start or End
    And no separate Start and End form is shown

  # trip-workflow.spec.ts: "While planning, the trip is read-only and nothing is exported" (chromium; a real ready route,
  # then the job held at "solving", W4). D208 F2. Inner: PlanPanel.test.ts, tripPhase.test.ts.
  @US-23 @J-01 @ui @edge
  Scenario: While planning, the trip is read-only and nothing is exported
    Given "Alpi Occidentali giugno 2027" has a ready route on real roads
    When Marco presses "Plan the route" after adding "Lago del Moncenisio"
    Then the status reads "Planning…" with a progress indicator
    And "Stop and use best so far" is the only main action
    And the list cannot be changed and "Add" is not offered
    And no "Export GPX" is offered, not even for the earlier route

  # trip-workflow.spec.ts: "Stopping shows the best route found so far" (chromium; the held job ends with a ready run
  # whose answer carries the stopped flag and its line, W4). D285: the line is in Details, the card carries the tag.
  @US-23 @US-06b @J-01 @ui @edge
  Scenario: Stopping shows the best route found so far
    Given "Alpi Occidentali giugno 2027" is being planned and "Stop and use best so far" is offered
    When Marco presses "Stop and use best so far" and the planner ends with a ready route
    Then the page shows "Your route" with the status "Route ready"
    And the summary card shows the tag "Not fully optimised"
    And "Details" shows the planner's line "not fully optimised (stopped)" word for word

  # trip-workflow.spec.ts: "Edit trip goes back to building and the shown route goes out of date" (chromium; real: a
  # ready route on the offline road map, then "Click on the map to add"). D259, D288.
  @US-23 @US-16 @J-01 @HC-4 @ui @edge
  Scenario: Edit trip goes back to building and the shown route goes out of date
    Given the route of "Alpi Occidentali giugno 2027" is ready on real roads
    When Marco presses "Edit trip" and adds "Lago del Moncenisio" by clicking on the map
    Then the page shows "Build the trip" with "Lago del Moncenisio" in the list
    And the status reads "Out of date, plan again"
    And the main action is "Plan the route"

  # trip-workflow.spec.ts: "A refusal keeps Marco on Build the trip with the planner's own words" (chromium; real: the
  # planner refuses a plan without a Start). D211: the planner's refusal, not reworded.
  @US-23 @J-01 @ui @error
  Scenario: A refusal keeps Marco on Build the trip with the planner's own words
    Given "Assietta weekend" has no Start chosen
    When Marco presses "Plan the route"
    Then the planner's refusal "Set the Start before calculating" is shown word for word
    And the page stays on "Build the trip" with the list unchanged

  # ===================== US-24 The route is the main result: card and timeline linked to the map (J-01) ==========

  # trip-workflow.spec.ts: "On a laptop the summary card and the first steps are in view" (chromium 1440 x 900; the run
  # detail rewritten to a Valhalla run, W4). Inner: RouteCard.test.ts. Replaces slice 12 "On a laptop the map is the
  # main surface", last line (D290).
  @US-24 @J-01 @ui @desktop
  Scenario: On a laptop the summary card and the first steps are in view
    Given the route of "Alpi Occidentali giugno 2027" is ready on real roads
    When Marco opens the project in a 1440 x 900 px window
    Then the page shows "Your route" with a summary card holding the total distance and time, the road and off-road split, and "Real roads"
    And the first steps of the itinerary are in view below the card without scrolling
    And the main action is "Export GPX" and "Edit trip" is offered

  # trip-workflow.spec.ts: "An estimate route says Estimate in the card and on the map" (chromium; real: a plan on the
  # offline road map; the download's file name is the planner's). D267, D268.
  @US-24 @US-21 @J-01 @J-04 @ui @edge
  Scenario: An estimate route says Estimate in the card and on the map
    Given the route of "Assietta weekend" took its road legs from the offline road map
    When Marco opens the project and presses "Export GPX"
    Then the summary card says "Estimate" and the map says "Estimate"
    And "Real roads" is not shown
    And the file is "assietta-weekend-run1-estimate.gpx"

  # trip-workflow.spec.ts: "Selecting a step moves the map to it" (chromium; Valhalla run by rewrite, W4; the map's
  # published centre and zoom, as slice 12's `__overlandRunMap`). Inner: Itinerary.test.ts, runMap.test.ts (bounds).
  @US-24 @J-01 @ui
  Scenario: Selecting a step moves the map to it
    Given the route of "Alpi Occidentali giugno 2027" is ready on real roads
    When Marco selects step 3 "Strada dell'Assietta" in the itinerary
    Then the map zooms to "Strada dell'Assietta"
    And marker 3 on the map and step 3 in the itinerary are highlighted

  # trip-workflow.spec.ts: "Selecting a stop on the map highlights its step" (chromium; geometry and detail rewritten to
  # the owner's stop order with Colle del Sommeiller as stop 7, W4).
  @US-24 @J-01 @ui
  Scenario: Selecting a stop on the map highlights its step
    Given the route of "Alpi Occidentali giugno 2027" is ready on real roads
    When Marco selects marker 7 on the map
    Then step 7 "Colle del Sommeiller" is highlighted and scrolled into view in the itinerary

  # trip-workflow.spec.ts: "A retrace is its own step, linked to its own line" (chromium; retrace added to the answers,
  # W4, as slice 12's `withSommeillerRetrace`). US-19, D279.
  @US-24 @US-19 @J-01 @J-02 @ui @edge
  Scenario: A retrace is its own step, linked to its own line
    Given the route of "Alpi Occidentali giugno 2027" retraces "Colle del Sommeiller" for 12.4 km off-road
    When Marco selects the retrace step
    Then the map zooms to the retrace line
    And the step shows the retrace's reason word for word and 12.4 km off-road
    And "Colle del Sommeiller" appears once as a trail step and once as a retrace step

  # trip-workflow.spec.ts: "On a phone the map follows the selected step" (webkit-iphone14; Valhalla run by rewrite).
  @US-24 @J-01 @ui @phone @edge
  Scenario: On a phone the map follows the selected step
    Given the route of "Alpi Occidentali giugno 2027" is ready on real roads
    When Giulia taps step 5 "Briancon" on her 390 px wide iPhone
    Then the map comes into view zoomed to "Briancon" with marker 5 highlighted
    And no page scrolls sideways and every step she can tap is at least 44 px high

  # ===================== US-25 The status in user words, engine details behind Details (J-01, J-04) ==============

  # trip-workflow.spec.ts: "Every status has its own words and look: <status>" (chromium; one test per row; Loading,
  # Planning and Couldn't plan by rewritten answers, W4; Out of date real). Replaces slice 12's plan-state outline (D290).
  # Inner: planState.test.ts (labels, D284), PlanPanel.test.ts.
  @US-25 @J-01 @ui
  Scenario Outline: Every status has its own words and look
    Given the plan of "Alpi Occidentali giugno 2027" is <state>
    When Marco opens the project
    Then the status reads "<status>"
    And its look differs from the look of every other status, also without colour

    Examples:
      | state                                 | status                  |
      | not computed yet                      | No plan yet             |
      | being loaded                          | Loading                 |
      | being planned                         | Planning…               |
      | ready, run #7                         | Route ready             |
      | failed, run #7, after a ready run #6  | Couldn't plan           |
      | ready, run #4, trip changed since     | Out of date, plan again |

  # trip-workflow.spec.ts: "Engine details wait behind one closed Details" (chromium; a real memo reuse: the same trip
  # planned twice; the planner's lines are read from its answer). D285. Inner: RunDetails.test.ts.
  @US-25 @J-01 @ui
  Scenario: Engine details wait behind one closed Details
    Given run #7 of "Alpi Occidentali giugno 2027" is ready on real roads and reused the identical plan of run #6
    When Marco opens the project
    Then "Plan run #7", the provider line, "Planned 23 items in 0.3 s", "Reused the identical plan of run #6" and "Re-optimise (ignore previous result)" are not in view
    And one "Details" is shown, closed
    When Marco opens "Details"
    Then all five are shown, the planner's lines word for word and in the planner's order

  # trip-workflow.spec.ts: "Couldn't plan keeps the previous route and its export" (chromium; failed run #7 added to the
  # run list, W4, as slice 12's failRunFive). D208 (user decision), D276, brief outcome check 3.
  @US-25 @J-01 @J-04 @A-4 @ui @error
  Scenario: Couldn't plan keeps the previous route and its export
    Given run #6 of "Alpi Occidentali giugno 2027" is ready on real roads and run #7 failed on its time limit
    When Marco opens the project
    Then the status reads "Couldn't plan" with "No valid route found within the time limit - plan run #7 failed" word for word
    And the summary card and the itinerary of run #6 stay, under the heading "Previous route"
    And the "Details" of the previous route names "Plan run #6"
    And "Export GPX" of the previous route is offered and gives "alpi-occidentali-giugno-2027-run6.gpx"
    And the failed run offers no export and shows no "Estimate"

  # trip-workflow.spec.ts: "Couldn't plan without an earlier route keeps Marco on Build the trip" (chromium; the job
  # answer rewritten to the planner's failure for an unanswering engine, W4). ADR-013, US-10a.
  @US-25 @US-10a @J-01 @ui @error @infrastructure-failure
  Scenario: Couldn't plan without an earlier route keeps Marco on Build the trip
    Given "Assietta weekend" has no ready route and the routing engine does not answer
    When Marco presses "Plan the route"
    Then the status reads "Couldn't plan" with "Routing engine unreachable - nothing was changed. Try again later." word for word
    And the page stays on "Build the trip" with "Plan the route" as its main action
    And no "Export GPX" is offered

  # trip-workflow.spec.ts: "An out-of-date route asks to be planned again and can still be exported" (chromium; real: a
  # plan on the offline road map, then a place added). A-10, D259, D268. Replaces slice 12 "A stale estimate shows both
  # labels" (D290).
  @US-25 @US-05 @J-01 @J-04 @HC-4 @ui @edge
  Scenario: An out-of-date route asks to be planned again and can still be exported
    Given run #4 of "Alpi Occidentali giugno 2027" is an estimate and Marco added "Lago del Moncenisio" since
    When Marco opens the project
    Then the status reads "Out of date, plan again" and the card still says "Estimate"
    And the route of run #4 stays on show with "Plan the route" as the main action
    And "Export GPX" is still offered and gives "alpi-occidentali-giugno-2027-run4-estimate.gpx"

  # trip-workflow.spec.ts: "Planning an unchanged trip with a retrace reuses the route and keeps each stop once"
  # (chromium; a real memo reuse, the retrace added to both runs' answers, W4). D279, D73.
  @US-25 @US-19 @J-01 @J-02 @ui @edge
  Scenario: Planning an unchanged trip with a retrace reuses the route and keeps each stop once
    Given run #4 of "Alpi Occidentali giugno 2027" is ready and retraces "Colle del Sommeiller"
    When Marco presses "Edit trip" and then "Plan the route" without changing anything
    Then the status reads "Route ready"
    And the itinerary shows "Colle del Sommeiller" once as a trail step and once as a retrace step
    And "Details" shows "Reused the identical plan of run #4" and offers "Re-optimise (ignore previous result)"

  # trip-workflow.spec.ts: "The planner's notices stay in view" (chromium; the answer to "Plan the route" carries the
  # planner's notice and the job is held, W4: 66 real items would take minutes on CI). D146.
  @US-25 @J-01 @ui @edge
  Scenario: The planner's notices stay in view
    Given "Alpi Occidentali giugno 2027" has 64 Included items besides its Start and End
    When Marco presses "Plan the route"
    Then "Large project - calculation may take longer than 3 minutes" is shown word for word outside "Details"

  # ===================== US-26 A calm map on which the route stands out (J-01) =====================

  # test_slice_12b.py (HTTP API): `GET /api/config/map` with the base map left to its default (D287).
  @US-26 @J-01 @driving_port
  Scenario: The planner names the light base map and its credit and keeps the Terrain map
    Given the planner settings choose the OpenTopoMap tiles with their attribution
    And the planner settings leave the light base map to its default
    When Marco opens any map
    Then the light base map is OpenFreeMap "Positron" with the credit "© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors"
    And the map loads its tiles from OpenTopoMap
    And the attribution "OpenTopoMap" is always shown

  # test_slice_12b.py (real server process, as slice 09's tile guard): one `health.startup.refused` line.
  @US-26 @J-02 @NFR-4 @driving_port @driving_adapter @wiring_e2e @error @security
  Scenario: A light base map address carrying a private access key stops the planner at start-up
    Given the planner settings use a light base map address that carries a private access key
    When Marco starts the planner
    Then the planner refuses to start
    And the planner log names the light base map setting and the key's parameter, never the key itself

  # trip-workflow.spec.ts: "The map opens on a calm base map with its credit" (chromium; the style address answered with
  # the test's own small style). Inner: TripMap.svelte.test.ts (style adoption, credit).
  @US-26 @J-01 @ui
  Scenario: The map opens on a calm base map with its credit
    Given the route of "Alpi Occidentali giugno 2027" is ready on real roads
    When Marco opens the project
    Then the map shows the light base map
    And the map credits the light base map's source

  # trip-workflow.spec.ts: "Terrain switches to the topographic map and back" (chromium; layer visibility and credit).
  @US-26 @J-01 @ui
  Scenario: Terrain switches to the topographic map and back
    Given Marco is looking at the route of "Alpi Occidentali giugno 2027" on the light base map
    When he presses "Terrain"
    Then the map shows the topographic map with its own credit and the same route
    When he presses "Terrain" again
    Then the map shows the light base map again

  # trip-workflow.spec.ts: "The route stands out on both base maps: <base>" (chromium; one test per row; layer order
  # read from the map's style, line and casing colours through tests/e2e/contrast.ts). Inner: runMap.test.ts.
  @US-26 @J-01 @ui
  Scenario Outline: The route stands out on both base maps
    Given the route of "Alpi Occidentali giugno 2027" is shown on the <base> map
    When Marco views the whole trip
    Then the road, trail and retrace lines are drawn with a light outline above the base map's labels
    And each line has a contrast of at least 3:1 against the base map around it

    Examples:
      | base        |
      | light base  |
      | topographic |

  # trip-workflow.spec.ts: "Road, trail and retrace stay apart on both base maps" (chromium; retrace added, W4).
  @US-26 @US-15 @US-19 @J-01 @ui @edge
  Scenario: Road, trail and retrace stay apart on both base maps
    Given the route of "Alpi Occidentali giugno 2027" includes "Strada dell'Assietta" and a retrace of "Colle del Sommeiller"
    When Marco views them on the light base map and on "Terrain"
    Then on each base map the road, the trail and the retrace differ in colour and the retrace also in line style

  # trip-workflow.spec.ts: "An estimate says so on the map on both base maps" (chromium; real offline-road-map run).
  @US-26 @US-21 @J-01 @J-04 @ui @edge
  Scenario: An estimate says so on the map on both base maps
    Given the route of "Assietta weekend" took its road legs from the offline road map
    When Marco views it on the light base map and on "Terrain"
    Then the map says "Estimate" on each

  # trip-workflow.spec.ts: "On a phone the map controls fit and can be tapped" (webkit-iphone14; real estimate run).
  @US-26 @J-01 @ui @phone @edge
  Scenario: On a phone the map controls fit and can be tapped
    Given the route of "Assietta weekend" is an estimate
    When Giulia opens it on her 390 px wide iPhone
    Then "Terrain", the "Estimate" chip and the map's credit do not overlap each other or a stop number
    And "Terrain" is at least 44 px high and 44 px wide

  # trip-workflow.spec.ts: "The route still shows when the base map does not load" (chromium; the Terrain tiles and the
  # light base map's style aborted in the browser).
  @US-26 @J-01 @ui @error @infrastructure-failure
  Scenario: The route still shows when the base map does not load
    Given the topographic tiles do not answer
    When Marco presses "Terrain" on the route of "Alpi Occidentali giugno 2027"
    Then the route lines, the stop numbers and the itinerary are still shown

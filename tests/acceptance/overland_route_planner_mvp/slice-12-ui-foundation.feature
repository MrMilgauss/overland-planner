# Slice 12 - a planner that looks and feels like a product. US-20 (J-01), US-21 (J-01, J-04), US-22 (J-02). No new
# planning behaviour (slice 12 OUT). Executable SSOT (D140). DESIGN D264-D273, orchestrator D274.
#
# Checking tool per scenario (D273):
#  - @driving_port: pytest-bdd at the HTTP API (test_slice_12.py, steps/ui_foundation_steps.py): the run detail's
#    `estimate` flag, the GPX file name and the trip name inside the file.
#  - @ui: Playwright, tests/e2e/ui-foundation.spec.ts (written in DELIVER; one `test.fixme` per scenario until then),
#    on chromium (desktop, and at 768 and 1440 px) and webkit-iphone14 (390 px), CI job 7 against the packaged planner
#    (offline road map). Data is seeded as the other specs do: the page itself (New project, Import, Add place, Set Start
#    and End, Calculate) and `page.request` to the planner's own API. States the packaged planner cannot reach on its own
#    (Loading, Planning, Failed, a Valhalla run, a K2 count above 0) are set by rewriting the planner's answer in the
#    browser (`page.route`, policy waiver W4). The inner checks of DESIGN D273 (vitest + jsdom: planState, PlanPanel,
#    RunMap, runMap, ProjectsPage, k2Acknowledgement) come with each scenario in DELIVER.
# "Calculate" and "Export GPX" are the stories' "Optimize" and "Download GPX" (D272). Outcomes, not pixels.

@slice-12
Feature: A planner that looks and feels like a product
  As Marco and Giulia, we want the planner to read as one product on a laptop, a tablet and a phone,
  so that we can tell what is selected, start a plan and say whether the route shown is real or an estimate.

  # ===================== US-20 One product: map first, one look, on any screen (J-01) =====================

  # ui-foundation.spec.ts: "On a laptop the map is the main surface" (chromium, 1440 px)
  @US-20 @J-01 @ui @desktop
  Scenario: On a laptop the map is the main surface
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    When Marco opens the project in a 1440 px wide window
    Then the map takes more of the window's width than any other part of the page
    And the stops, itinerary heading and totals of plan run #4 are beside the map without scrolling the page

  # ui-foundation.spec.ts: "On a phone nothing scrolls sideways and every target is touch-sized" (webkit-iphone14)
  @US-20 @J-01 @ui @phone
  Scenario: On a phone nothing scrolls sideways and every target is touch-sized
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    When Giulia opens the home page, the project and the Diagnostics page on her 390 px wide iPhone
    Then no page scrolls sideways
    And on the project page the itinerary and totals come below the map
    And every button, link and field she can tap is at least 44 px high and 44 px wide

  # ui-foundation.spec.ts: "At tablet width nothing overlaps" (chromium, 768 px)
  @US-20 @J-01 @ui @edge
  Scenario: At tablet width nothing overlaps
    Given plan run #4 of "Alpi Occidentali giugno 2027" has been computed
    When Marco opens the project in a 768 px wide window
    Then no control, label or panel overlaps another
    And no page scrolls sideways

  # ui-foundation.spec.ts: "Every page uses the same look and the controls are grouped by task" (chromium)
  @US-20 @J-01 @ui
  Scenario: Every page uses the same look and the controls are grouped by task
    Given Marco's project "Alpi Occidentali giugno 2027" exists
    When Marco opens the home page, the project page and the Diagnostics page
    Then every button, link and field uses the planner's shared look and none keeps the browser's plain look
    And the project page shows its controls in three labelled groups: "Plan", "Items" and "Start and end"

  # ui-foundation.spec.ts: "The theme follows the system and text stays readable outdoors" (chromium, dark and light)
  @US-20 @J-01 @ui @edge
  Scenario: The theme follows the system and text stays readable outdoors
    Given Marco's laptop is set to dark mode
    When he opens the project page of "Alpi Occidentali giugno 2027"
    Then the page is dark
    And in both the dark and the light look every text stands out from its background by at least 4.5 to 1

  # ui-foundation.spec.ts: "Keyboard focus is always visible" (chromium)
  @US-20 @J-01 @ui
  Scenario: Keyboard focus is always visible
    Given Marco is on the project page of "Alpi Occidentali giugno 2027"
    When he moves through the controls with the Tab key, from "Calculate" to "Export GPX"
    Then every control that receives focus shows a visible focus ring

  # ui-foundation.spec.ts: "The map stays readable on a phone at trip-wide zoom" (webkit-iphone14; the retrace comes from
  # the run detail rewritten in the browser, W4). Inner: runMap.test.ts (zoom-scaled arrows, label placement rule).
  @US-20 @J-01 @ui @phone @edge
  Scenario: The map stays readable on a phone at trip-wide zoom
    Given plan run #4 of "Alpi Occidentali giugno 2027" includes "Strada dell'Assietta" and a 12.4 km retrace of "Colle del Sommeiller"
    When Giulia views the whole trip on her 390 px wide iPhone
    Then the direction arrows are drawn smaller than when she zooms in on "Strada dell'Assietta"
    And no arrow covers a stop number
    And the "retrace" label covers no stop number, or waits for her to zoom in

  # ===================== US-21 Plan state and whether its roads are real (J-01, J-04) =====================

  # ui-foundation.spec.ts: "Every plan state has its own label and look" (chromium; one test per row; Loading, Planning
  # and Failed by rewritten answers, W4). Inner: planState.test.ts, PlanPanel.test.ts.
  @US-21 @J-01 @ui
  Scenario Outline: Every plan state has its own label and look
    Given the plan of "Alpi Occidentali giugno 2027" is <state>
    When Marco opens the project
    Then the plan area carries the label "<label>"
    And its look differs from the look of every other plan state, also without colour

    Examples:
      | state                           | label       |
      | not computed yet                | No plan yet |
      | being loaded                    | Loading     |
      | being planned (Stop is offered) | Planning    |
      | done, plan run #6               | Plan run #6 |
      | Failed, plan run #5             | Failed      |
      | Stale, plan run #4              | Stale       |

  # ui-foundation.spec.ts: "While planning, Stop is offered" (chromium, the job answer held at "running", W4)
  @US-21 @J-01 @ui
  Scenario: While planning, Stop is offered
    Given Marco pressed "Calculate" for "Alpi Occidentali giugno 2027"
    When the plan is being worked on
    Then the plan area is labelled "Planning"
    And "Stop and use best so far" is offered

  # ui-foundation.spec.ts: "A Failed run shows the label Failed and the planner's own words" (chromium, W4)
  @US-21 @J-01 @ui @error
  Scenario: A Failed run shows the label Failed and the planner's own words
    Given plan run #5 of "Alpi Occidentali giugno 2027" failed on its time limit
    When Marco opens the project
    Then the plan area carries the label "Failed"
    And it shows "No valid route found within the time limit - plan run #5 failed" word for word
    And plan run #5 offers no "Export GPX"
    And the Failed run carries no "estimate" marker
    And the export of the older plan run #4 stays offered, named with its number

  # ui-foundation.spec.ts: "A plan on the offline road map is marked as an estimate" (chromium and webkit-iphone14:
  # the packaged planner plans on the offline road map, so this run is real, not rewritten)
  @US-21 @J-01 @J-04 @ui
  Scenario: A plan on the offline road map is marked as an estimate
    Given plan run #4 of "Alpi Occidentali giugno 2027" took its road legs from the offline road map
    When Marco opens the project
    Then "estimate" is shown next to the heading "Plan run #4"
    And the map of plan run #4 carries the same "estimate" marker

  # test_slice_12.py (HTTP API): the run detail of plan run #4
  @US-21 @J-01 @J-04 @driving_port
  Scenario: The planner reports a plan on the offline road map as an estimate
    Given plan run #4 of "Alpi Occidentali giugno 2027" took its road legs from the offline road map
    When Marco opens plan run #4
    Then plan run #4 is reported as an estimate

  # test_slice_12.py (HTTP API): the export of plan run #4 (file name and trip name)
  @US-21 @J-04 @driving_port
  Scenario: The GPX of an offline-road-map plan says it is an estimate
    Given plan run #4 of "Alpi Occidentali giugno 2027" took its road legs from the offline road map
    When Marco downloads its GPX
    Then he downloads "alpi-occidentali-giugno-2027-run4-estimate.gpx"
    And the trip name inside the file is "Plan run #4 (estimate)"

  # test_slice_12.py (HTTP API): plan run #6 on the real Valhalla adapter (synthetic engine, as slice 06a)
  @US-21 @J-01 @J-04 @driving_port @edge
  Scenario: A plan on real roads is not called an estimate, in the planner or in its GPX
    Given plan run #6 of "Alpi Occidentali giugno 2027" took its road legs from Valhalla
    When Marco opens plan run #6 and downloads its GPX
    Then plan run #6 is not reported as an estimate
    And he downloads "alpi-occidentali-giugno-2027-run6.gpx"
    And the trip name inside the file is "Plan run #6"

  # ui-foundation.spec.ts: "A plan on real roads shows no estimate marker" (chromium; run detail rewritten to a Valhalla
  # run, W4). Inner: PlanPanel.test.ts and RunMap.test.ts with `estimate: false`.
  @US-21 @J-01 @ui @edge
  Scenario: A plan on real roads shows no estimate marker
    Given plan run #6 of "Alpi Occidentali giugno 2027" took its road legs from Valhalla
    When Marco opens the project
    Then the plan area carries the label "Plan run #6"
    And no "estimate" marker is shown, neither by the heading nor on the map

  # ui-foundation.spec.ts: "A stale estimate shows both labels" (chromium; real: offline road map, then a place added)
  @US-21 @J-01 @HC-4 @ui @edge
  Scenario: A stale estimate shows both labels
    Given plan run #4 of "Alpi Occidentali giugno 2027" took its road legs from the offline road map
    And Marco has added "Lago del Moncenisio" since plan run #4
    When Marco opens the project
    Then the plan area carries the label "Stale"
    And "estimate" is still shown next to the heading "Plan run #4"

  # ui-foundation.spec.ts: "A project with no plan yet says so and points to Calculate" (chromium and webkit-iphone14;
  # real: a new project). Adds to the outline's "No plan yet" row what an empty project offers (D264, D266).
  @US-21 @J-01 @ui @edge
  Scenario: A project with no plan yet says so and points to Calculate
    Given Marco has just created the project "Assietta weekend"
    When he opens it
    Then the plan area carries the label "No plan yet" and the hint "Press Calculate to plan this trip."
    And the map area says "The map shows the plan once one is computed."
    And no "Export GPX" is offered

  # ===================== US-22 The home page tells when a plan broke a hard rule (J-02, K2) =====================
  # The K2 count comes from the Diagnostics answer, rewritten in the browser (W4): a real rule-breaking run cannot be
  # produced by the packaged planner (waiver W1). The acknowledgement lives in this browser only (D271).

  # ui-foundation.spec.ts: "A rule-breaking plan run raises a banner on the home page" (chromium and webkit-iphone14)
  @US-22 @J-02 @HC-1 @kpi @K2 @ui
  Scenario: A rule-breaking plan run raises a banner on the home page
    Given the Diagnostics page counts 1 plan run that broke a hard rule
    When Marco opens the home page
    Then a warning banner says a plan run broke one of the planner's rules and shows the count 1
    And it links to the Diagnostics page

  # ui-foundation.spec.ts: "An acknowledged banner stays away in this browser" (chromium)
  @US-22 @J-02 @ui
  Scenario: An acknowledged banner stays away in this browser
    Given the warning banner shows the count 1 on Marco's laptop
    When Marco acknowledges it and opens the home page again
    Then no warning banner is shown

  # ui-foundation.spec.ts: "The banner comes back when the count grows" (chromium)
  @US-22 @J-02 @ui @edge
  Scenario: The banner comes back when the count grows
    Given Marco acknowledged the warning banner at the count 1
    And the Diagnostics page now counts 2 plan runs that broke a hard rule
    When Marco opens the home page
    Then the warning banner is shown with the count 2

  # ui-foundation.spec.ts: "Another browser still sees the banner" (two browser contexts: Marco's laptop, Giulia's phone)
  @US-22 @J-02 @ui @edge
  Scenario: Another browser still sees the banner
    Given Marco acknowledged the warning banner at the count 1 on his laptop
    When Giulia opens the home page on her phone
    Then she sees the warning banner with the count 1

  # ui-foundation.spec.ts: "No banner when no plan run broke a rule" (chromium; the real Diagnostics answer, count 0)
  @US-22 @J-02 @ui @edge
  Scenario: No banner when no plan run broke a rule
    Given the Diagnostics page counts 0 plan runs that broke a hard rule
    When Marco opens the home page
    Then no warning banner is shown

  # ui-foundation.spec.ts: "The home page still works when the count cannot be read" (chromium; Diagnostics answers 503)
  @US-22 @J-02 @ui @error @infrastructure-failure
  Scenario: The home page still works when the count cannot be read
    Given the Diagnostics answer cannot be read
    When Marco opens the home page
    Then no warning banner is shown
    And his projects are listed as usual

  # ui-foundation.spec.ts: "The banner still shows when the browser refuses to keep the acknowledgement" (chromium;
  # browser storage made to refuse every write and read). D271: a failed storage read shows the banner.
  @US-22 @J-02 @ui @error @infrastructure-failure
  Scenario: The banner still shows when the browser refuses to keep the acknowledgement
    Given the Diagnostics page counts 1 plan run that broke a hard rule
    And Marco's browser refuses to keep anything for the planner
    When Marco acknowledges the warning banner and opens the home page again
    Then the warning banner is shown with the count 1
    And his projects are listed as usual

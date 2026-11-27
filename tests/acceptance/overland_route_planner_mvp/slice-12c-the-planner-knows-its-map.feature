# Slice 12c - the planner knows its map. US-27, US-28, US-29, US-30, US-31 (J-06, J-05, J-01). Executable SSOT (D140).
# DESIGN D299-D311, revised by D313 and D314 (ADR-013 Amendment 5, ADR-019, ADR-020); DISTILL D312 (revised after the
# consolidated review).
#
# Checking tool per scenario:
#  - @ui: Playwright, tests/e2e/road-map.spec.ts (one `test.fixme` per scenario, one per outline row, until DELIVER), on
#    chromium (desktop, 1440 x 900 set per test) and webkit-iphone14 (390 px), CI job 7, against the packaged planner
#    with the offline road map and a fixture volume. Data is seeded by the page itself and by `page.request` to the
#    planner's own API; the two foreign services are answered by the spec's own routes (policy row "Region catalogue
#    and place search"). Waiver W4 as 12b.
#  - @driving_port: pytest-bdd (test_slice_12c.py, steps/road_map_steps.py): the real app from the composition root,
#    driven through its HTTP API in-process, with fixture volumes under tmp_path.
#  - @real-io @adapter-integration: the same real app with each real driven adapter against real I/O: two local fake
#    servers that record every request (the region service, the place search service), real polygon files from
#    Geofabrik, real map folders and change files. File and storage details live in the step bodies, never here.
#  - @script @offline: pytest-bdd on the real shell scripts under tests/deploy's seams (shims for docker, crontab,
#    flock, df, curl; FakePi), as the refresh tests of D277.
#  - Tags: @US-n traces each scenario to its story; @error / @edge / @infrastructure-failure mark error and edge cases.
#
# Scenario wording is business language (review blocker): technical details (files, folders, keys, exit codes, the
# crontab) are in the step bodies. DISTILL adapts the DISCUSS examples where DESIGN changed the details:
#  - Examples that add "Germany" add Portugal (D313 O1); sizes and times follow D305 (6.8 GB: 41 and 58 minutes; the
#    eight regions plus Utah, 7.5 GB: 45 and 64 minutes).
#  - Region names are the catalogue's own (Rhone-Alpes, Provence Alpes-Cote-d'Azur, Midi-Pyrenees ...).
#  - "Roads loaded for" shows the served map's regions, which exist only after a rebuild from the app; today's map
#    (built on 26 November 2026) is "Map coverage unknown" (D313 Q1).
#  - US-29's "caching OUT" is overridden for answers kept in memory only (D307). No contact detail is ever sent (D313 Q7).
# Region sizes are the fixture's: today's eight regions are 6.4 GB, Portugal 0.4 GB, Utah 1.1 GB, North America 14 GB.
# "Today" is 28 November 2026 at 21:00 UTC and the served map was built on 27 November 2026, unless a scenario says so.

@slice-12c @pending
Feature: The planner knows its map
  As the owner, Marco and Giulia, we want to choose which regions have roads, see when the road map was built and
  whether a rebuild worked, be told before we plan that a place is outside the map, and find a place by its name,
  so that nobody edits a file, nobody plans for an hour to learn a place was unreachable, and the house's data stays
  in the house.

  # ===================== US-27 See which regions have roads and choose which to add or remove =====================

  @US-27 @ui
  Scenario: The Road map screen shows what is loaded
    Given the road map was rebuilt from the app and the served map has the eight regions, with map data of 27 November 2026
    When Marco opens "Road map" from the header beside the projects
    Then he sees the eight regions by name and "Map data: 27 November 2026"
    And no file, script or setting needs to be edited to change them

  @US-27 @ui @edge
  Scenario: Before the first rebuild from the app the screen says the regions are unknown
    Given the served map was built on 26 November 2026, before the app kept the regions of a map
    When Marco opens "Road map"
    Then he sees "Map coverage unknown" with the map date and no list of regions
    And he is offered "Refresh map data" to build the same eight regions again

  @US-27 @ui
  Scenario: A region is added by searching the free list of regions by name
    Given the road map has the eight regions and Marco is on the "Road map" screen
    When he searches "Utah" and adds the result
    Then "Utah" is listed as "to be added" and the loaded regions are still the eight
    And the screen says Utah is not linked by land to the other regions, as information only

  @US-27 @ui @edge
  Scenario: A region is removed as a pending change
    Given the loaded regions include Austria
    When Marco removes Austria
    Then Austria is listed as "to be removed" and is still loaded until a rebuild ends well

  @US-27 @ui
  Scenario: Size and time are shown before applying
    Given Marco has added Portugal
    Then the screen shows "Total download 6.8 GB", about 58 minutes in all and about 41 without planning

  @US-27 @ui @error
  Scenario: Too big is refused with the size
    Given Marco has added Portugal
    When he adds "North America" and the total goes above the limit of 8 GB
    Then the screen refuses it, saying the size and the limit, and the pending change is unchanged

  @US-27 @driving_port
  Scenario: The planner names the regions and the date of the served map
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When Marco asks the planner what road map it serves
    Then the planner names Italy, Spain, Switzerland, Austria, Rhone-Alpes, Provence Alpes-Cote-d'Azur, Languedoc-Roussillon and Midi-Pyrenees
    And the map data is dated 27 November 2026 and the regions total 6.4 GB
    And no change is pending

  @US-27 @driving_port @edge
  Scenario: Before the first rebuild from the app the planner gives the map date and no regions
    Given the served map was built on 26 November 2026, before the app kept the regions of a map
    When Marco asks the planner what road map it serves
    Then the planner says the map coverage is unknown and names no region
    And the map data is still dated 26 November 2026

  @US-27 @driving_port
  Scenario Outline: A region is found in the catalogue by name, with its parent and what the map already covers
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When the owner searches the catalogue for "<name>"
    Then the answer holds "<name>", part of "<parent>", of <size> GB, <mark>

    Examples:
      | name  | parent                   | size | mark                       |
      | Utah  | United States of America | 1.1  | not yet in the map         |
      | Spain | Europe                   | 1.4  | already in the map         |

  @US-27 @driving_port @edge
  Scenario: Two regions with the same name are told apart by their parent
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When the owner searches the catalogue for "Georgia"
    Then the answer holds two regions named "Georgia", one part of "Europe" and one part of "United States of America"

  @US-27 @driving_port @error @edge
  Scenario: A search for a region needs at least two letters
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When the owner searches the catalogue for "U"
    Then the planner refuses the search and says the name is too short

  @US-27 @driving_port @real-io @adapter-integration
  Scenario: A change is summarised before it is written, and only the chosen region's border is fetched
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When the owner asks what adding Portugal would cost
    Then the summary says 6.8 GB to download, planning paused about 41 minutes and the rebuild about 58 minutes
    And nothing is pending
    And the border of Portugal was fetched, and no other border

  @US-27 @US-31 @driving_port
  Scenario: Planning a change leaves the served map as it is
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When the owner plans the change adding Portugal for tonight at 02:00
    Then the change is pending, to be started on 29 November 2026 at 02:00 UTC, adding Portugal and removing nothing
    And the regions served are still the eight

  @US-27 @driving_port @error
  Scenario Outline: A change that cannot be applied is refused with the reason and nothing is written
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When the owner plans the change adding <region>
    Then the planner refuses it, <reason>
    And nothing is pending

    Examples:
      | region        | reason                                                          |
      | France        | because it contains Rhone-Alpes, which is already in the map    |
      | North America | because the download would be 20.4 GB and the limit is 8 GB    |
      | Atlantis      | because that region is not in the catalogue                     |

  @US-27 @driving_port @edge
  Scenario: A region far from the others is information, not a refusal
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When the owner asks what adding Utah would cost
    Then the summary says 7.5 GB to download, planning paused about 45 minutes and the rebuild about 64 minutes
    And the summary says Utah is not linked by land to the other regions
    And the change can still be applied

  @US-27 @driving_port @error @infrastructure-failure
  Scenario: Changing the road map is not offered when the changes cannot be stored
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the place where changes are kept cannot be written
    When Marco asks the planner what road map it serves
    Then the planner says changing the road map is not available right now
    And the regions are still named
    And the planner reports that changing the road map is unavailable

  @US-27 @driving_port @error @infrastructure-failure
  Scenario: A change is refused when the changes cannot be stored
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the place where changes are kept cannot be written
    When the owner plans the change adding Portugal
    Then the planner refuses it, because changes are not available

  # --- US-27 driven adapters: the region catalogue, the served-map reader (real I/O) ---

  @US-27 @driving_port @real-io @adapter-integration
  Scenario: The catalogue is fetched with the planner's name and only region details are asked for
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When the owner searches the catalogue for "Utah"
    Then the catalogue was fetched by a client that names itself as the planner
    And only the regions of the answers were asked about, never a project, a trail or a place

  @US-27 @driving_port @real-io @adapter-integration
  Scenario: The catalogue is kept, so a restarted planner does not ask for it again
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the owner has searched the catalogue for "Utah"
    And the planner has been restarted
    When the owner searches the catalogue for "Italy"
    Then the catalogue was not fetched again

  @US-27 @driving_port @real-io @adapter-integration @edge
  Scenario: The catalogue is fetched again after a week
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the owner has searched the catalogue for "Utah"
    And 8 days have passed
    When the owner searches the catalogue for "Utah"
    Then the catalogue was fetched again

  @US-27 @driving_port @real-io @adapter-integration @error @infrastructure-failure
  Scenario: The kept catalogue is used when the region service does not answer
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the catalogue was fetched 8 days ago
    And the region service does not answer
    When the owner searches the catalogue for "Utah"
    Then the answer holds "Utah"
    And the planner does not report the catalogue as unavailable

  @US-27 @driving_port @real-io @adapter-integration @edge
  Scenario: The size of a region is remembered
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the owner has searched the catalogue for "Utah"
    When the owner searches the catalogue for "Utah"
    Then the size of Utah was not asked again

  @US-27 @driving_port @real-io @adapter-integration
  Scenario: The served map is the one whose map data carries the date the Pi reports
    Given the Pi holds the maps of 1 November and 27 November, each with its regions
    And the Pi reports its map data is of 27 November
    When Marco asks the planner what road map it serves
    Then the planner names the regions of the map of 27 November and its map date

  @US-27 @driving_port @real-io @adapter-integration @edge
  Scenario: After a rollback the older map is the one served
    Given the Pi holds the maps of 1 November and 27 November, each with its regions
    And the Pi reports its map data is of 1 November
    When Marco asks the planner what road map it serves
    Then the planner names the regions of the map of 1 November and its map date

  @US-27 @driving_port @real-io @adapter-integration @error @edge
  Scenario Outline: A map whose regions cannot be read is unknown, never an error
    Given the Pi holds the map of 27 November with <fault>
    And the Pi reports its map data is of 27 November
    When Marco asks the planner what road map it serves
    Then the planner says the map coverage is unknown and names no region
    And the planner still works

    Examples:
      | fault                                              |
      | no list of regions                                 |
      | a list of regions of a version it does not know    |
      | a list of regions cut short                        |
      | no place for maps at all                           |

  @US-27 @driving_port @real-io @adapter-integration @infrastructure-failure @error
  Scenario: A damaged region border is reported as a reason, and the map stays unknown
    Given the Pi holds the map of 27 November with a region border that is not a border
    And the Pi reports its map data is of 27 November
    When Marco asks the planner what road map it serves
    Then the planner says the map coverage is unknown and names no region
    And the planner reports that it cannot read the regions of the map

  @US-27 @driving_port @real-io @adapter-integration @edge
  Scenario: While the Pi is busy building, the last known map is still named
    Given the Pi holds the maps of 1 November and 27 November, each with its regions
    And the Pi reports its map data is of 27 November
    And Marco has asked the planner what road map it serves
    And the Pi is busy building and gives no map date
    When Marco asks the planner what road map it serves
    Then the planner names the regions of the map of 27 November and its map date

  @US-27 @driving_port @real-io @adapter-integration
  Scenario: A pending change is kept ready for the helper
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When the owner plans the change adding Portugal and removing Austria for tonight at 02:00
    Then the planner keeps the change ready for the helper, with the eight regions of the new map, the start time and what is added and removed
    And the planner leaves the list of the map's regions to the rebuild

  @US-27 @US-31 @driving_port @real-io @adapter-integration
  Scenario: A cancelled change can no longer be taken by the helper
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the owner has planned the change adding Portugal for tonight at 02:00
    When the owner cancels it
    Then nothing is pending and the regions served are still the eight
    And the helper is no longer given the change

  # ===================== US-28 The page shows the regions and the map date, and warns when outside =====================

  @US-28 @ui
  Scenario: Build the trip shows the regions and the map date
    Given after a rebuild from the app the served map has the eight regions, with map data of 27 November 2026
    When Marco opens "Alpi Occidentali giugno 2027" on Build the trip
    Then he sees "Roads loaded for" with those eight names and "Map data: 27 November 2026"
    And neither is inside "Details"
    And on a 390 px wide iPhone both are shown in full width text with no horizontal scroll

  @US-28 @ui @edge
  Scenario: A trail outside the map is warned at add time and on its row, and kept
    Given Marco is building "Spagna test"
    When he uploads "algarve.gpx", a trail in Portugal
    Then the page says "algarve" is outside the planner's road map and names the regions loaded
    And the trail stays in the list with an "Outside road map" tag on its row

  @US-28 @ui @edge
  Scenario: A place outside the map is warned when added by a click on the map
    Given Marco is building "Spagna test"
    When he adds "Chefchaouen" in Morocco by a click on the map
    Then it is kept and shows the warning when added and the tag on its row

  @US-28 @ui @edge
  Scenario: A place outside the map is warned when added by typed coordinates
    Given Marco is building "Spagna test"
    When he adds "Lagos" in Portugal by typed coordinates
    Then it is kept and shows the warning when added and the tag on its row

  @US-28 @ui
  Scenario: A place inside the map shows no warning
    Given the loaded regions include Spain, as after a rebuild from the app
    When Marco adds "Cadaques" at 42.2889, 3.2776
    Then no warning is shown, at add time or on its row

  @US-28 @ui @error
  Scenario: Planning is not blocked by an outside item and says why it fails
    Given "Spagna test" holds "Torino" as Start and End and the Moroccan place "Chefchaouen"
    When Marco presses "Plan the route"
    Then the planner's own words are shown for the run that couldn't plan
    And the page names the regions with roads, as the row warning already did

  @US-28 @ui @error @edge
  Scenario: Without knowledge of the loaded map the page does not invent warnings
    Given the served map was built on 26 November 2026, before the app kept its regions, or the page cannot read them
    When Marco adds "Chefchaouen"
    Then the page says "Map coverage unknown" with the map date and shows no "Roads loaded for" list
    And it shows no outside-the-map warning or tag for any item

  @US-28 @ui @edge
  Scenario: Stops in areas not linked by land are warned on Build the trip
    Given after a rebuild from the app the loaded regions are the eight above and Utah, which is not linked by land to them
    When Marco's trip holds "Torino" as Start and the place "Moab" in Utah
    Then Build the trip says these stops are in areas not linked by land, so a trip between them would need a ferry
    And "Plan the route" stays available

  @US-28 @driving_port @real-io @adapter-integration @edge
  Scenario Outline: A place is inside or outside the map by the borders of the regions, not by boxes
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And Marco is building "Spagna test"
    When Marco adds the place "<place>" at <latitude>, <longitude>
    Then the place is kept and is <verdict> the road map

    Examples:
      | place              | latitude | longitude | verdict |
      | Cadaques           | 42.2889  | 3.2776    | inside  |
      | Torino             | 45.0703  | 7.6869    | inside  |
      | Lagos              | 37.1028  | -8.6730   | outside |
      | Chefchaouen        | 35.1688  | -5.2636   | outside |
      | Andorra la Vella   | 42.5063  | 1.5218    | outside |
      | Moab               | 38.5733  | -109.5498 | outside |

  @US-28 @driving_port @edge
  Scenario Outline: A trail is outside when its entry or its exit is outside, the middle does not matter
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And Marco is building "Spagna test"
    When Marco adds a trail from <entry> through <middle> to <exit>
    Then the trail is kept and is <verdict> the road map

    Examples:
      | entry             | middle            | exit              | verdict |
      | Torino            | Chefchaouen       | Cadaques          | inside  |
      | Lagos             | Torino            | Cadaques          | outside |
      | Torino            | Cadaques          | Lagos             | outside |

  @US-28 @driving_port @error @edge
  Scenario: Without the regions of the map the planner says the coverage is unknown and warns nothing
    Given the served map was built on 26 November 2026, before the app kept the regions of a map
    And Marco is building "Spagna test"
    When Marco adds the place "Chefchaouen" at 35.1688, -5.2636
    Then the place is kept and the trip's coverage is unknown with no place named as outside

  @US-28 @driving_port @edge
  Scenario: A pending change does not alter what the trip is judged against
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the owner has planned the change adding Portugal
    And Marco is building "Spagna test"
    When Marco adds the place "Lagos" at 37.1028, -8.6730
    Then the place is kept and is outside the road map

  @US-28 @driving_port @edge
  Scenario: Stops in areas not linked by land are grouped, and the groups are named
    Given the road map was rebuilt from the app and the served map holds the eight regions and Utah, with map data of 27 November 2026
    And Marco is building "Spagna test"
    And Marco has added the place "Torino" at 45.0703, 7.6869
    When Marco adds the place "Moab" at 38.5733, -109.5498
    Then the trip's stops are in two groups of regions that are not linked by land
    And one group holds Torino and the other holds Moab

  @US-28 @driving_port @edge
  Scenario: Italy, southern France and Spain are linked by land
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And Marco is building "Spagna test"
    And Marco has added the place "Torino" at 45.0703, 7.6869
    When Marco adds the place "Cadaques" at 42.2889, 3.2776
    Then the trip's stops are in one group of regions linked by land

  @US-28 @driving_port @edge
  Scenario: Without southern France Spain is on its own
    Given the road map was rebuilt from the app and the served map holds Italy, Switzerland, Austria and Spain, with map data of 27 November 2026
    And Marco is building "Spagna test"
    And Marco has added the place "Torino" at 45.0703, 7.6869
    When Marco adds the place "Cadaques" at 42.2889, 3.2776
    Then the trip's stops are in two groups of regions that are not linked by land

  @US-28 @US-29 @driving_port
  Scenario: The map settings no longer name a road-map area and say whether place search is offered
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When Marco opens the map settings
    Then the map settings hold no road-map area
    And the map settings say place search is offered

  # ===================== US-29 I find a place by typing its name =====================

  @US-29 @ui
  Scenario: A place is found by name and joins the trip
    Given Marco is building "Assietta weekend" and has chosen "Search for a place" in "Add"
    When he types "Gorges du Verdon" and presses "Search"
    Then he sees results with their region names
    And after he picks "Gorges du Verdon, Provence-Alpes-Côte d'Azur, France" it is in the list as a place, with no warning when the road map was rebuilt from the app and covers it

  @US-29 @ui @edge
  Scenario: Nothing is sent until Marco presses Search, and the screen says what leaves the house
    Given the search form of "Add" is open
    When Marco types "Gorges du Verdon" without pressing Search
    Then no search is made
    And the form says "Only the words you type are sent, from your home connection, to OpenStreetMap's public place search (Nominatim). Your trip and files stay at home. Don't type personal details. Search © OpenStreetMap contributors."

  @US-29 @ui @error
  Scenario: No result gives a clear message
    Given the search form is open
    When Marco searches "Zxqvbn" and nothing is found
    Then he reads that nothing was found with a hint to add the place on the map
    And the trip is unchanged

  @US-29 @ui @error @infrastructure-failure
  Scenario: An unreachable or busy search service leaves the trip unchanged
    Given the search service does not answer, or answers that it is busy
    When Marco searches "Gorges du Verdon"
    Then he reads that the place search isn't answering and to try again later or add the place another way
    And the other three ways to add still work and the trip is unchanged

  @US-29 @ui @edge
  Scenario: A result outside the road map is added with the warning
    Given after a rebuild from the app the loaded regions are the eight of the served map
    When Marco searches "Lagos" and picks the result in Portugal
    Then "Lagos" is in the list with the outside-the-map warning of US-28, at add time and as an "Outside road map" tag on its row

  @US-29 @ui @edge
  Scenario: Pressing Search twice quickly sends one search
    Given Marco has typed "Gorges du Verdon"
    When he presses "Search" twice within a second
    Then one search is made and the results are shown once

  @US-29 @ui @phone @edge
  Scenario: On a phone the search form fits and opens in the page flow
    Given Marco opens "Add" on his 390 px wide iPhone
    When he chooses "Search for a place"
    Then the form and results open under the heading bar in the page flow, not covering "Plan the route" or any other control
    And every control is at least 44 px high and wide

  @US-29 @driving_port @real-io @adapter-integration
  Scenario: A place name is answered with up to five places, each with its region
    Given place search is switched on and answers "Gorges du Verdon" with one place
    When Marco searches for the place "Gorges du Verdon"
    Then the answer holds "Gorges du Verdon" in Provence-Alpes-Cote d'Azur, France, with its latitude and longitude
    And the search service was asked for a short list of places, each with its region
    And the search service saw a client that names itself as the planner

  @US-29 @driving_port @real-io @adapter-integration @edge
  Scenario: No contact detail is ever sent to the search service
    Given place search is switched on and answers "Gorges du Verdon" with one place
    When Marco searches for the place "Gorges du Verdon"
    Then the search service received no contact detail

  @US-29 @driving_port @real-io @adapter-integration @edge
  Scenario: Nothing is sent to the search service unless a search is asked for
    Given place search is switched on and answers "Gorges du Verdon" with one place
    And Marco has created a project and added a place to it
    When Marco opens the map settings
    Then the map settings say place search is offered
    And the search service has seen no request

  @US-29 @driving_port @real-io @adapter-integration @edge
  Scenario: Only the typed words reach the search service
    Given the shared household password is set in Marco's settings
    And place search is switched on and answers "Gorges du Verdon" with one place
    And Marco is building "Assietta weekend"
    When Marco searches for the place "Gorges du Verdon"
    Then the search service received the typed words and nothing of the trip, the project name or the household password

  @US-29 @driving_port @real-io @adapter-integration @edge
  Scenario: Two different searches in a row are a second apart
    Given place search is switched on and answers "Gorges du Verdon" and "Lagos"
    And Marco has searched for the place "Gorges du Verdon"
    When Marco searches for the place "Lagos"
    Then the search service was not asked twice within a second

  @US-29 @driving_port @real-io @adapter-integration @edge
  Scenario: The same search again is answered from memory and sends nothing
    Given place search is switched on and answers "Gorges du Verdon" with one place
    And Marco has searched for the place "Gorges du Verdon"
    When Marco searches for the place "Gorges du Verdon"
    Then both answers hold the same place
    And the search service saw one request

  @US-29 @driving_port @real-io @adapter-integration @edge
  Scenario: Pressing Search twice at once sends one search
    Given place search is switched on and answers "Gorges du Verdon" with one place
    When Marco presses search for "Gorges du Verdon" twice at once
    Then both answers hold the same place
    And the search service saw one request

  @US-29 @driving_port @real-io @adapter-integration @error
  Scenario: A name that matches nothing is an empty answer, not an error
    Given place search is switched on and answers "Zxqvbn" with no place
    When Marco searches for the place "Zxqvbn"
    Then the answer holds no place

  @US-29 @driving_port @real-io @adapter-integration @error @infrastructure-failure
  Scenario Outline: A search service that is busy, down or garbled leaves the trip unchanged
    Given place search is switched on and <fault>
    And Marco is building "Assietta weekend"
    When Marco searches for the place "Gorges du Verdon"
    Then the planner says the place search isn't answering
    And the trip holds the same items as before

    Examples:
      | fault                                       |
      | the search service answers that it is busy  |
      | the search service is not running           |
      | the search service answers an error         |
      | the search service answers nonsense         |

  @US-29 @driving_port @real-io @adapter-integration @error @infrastructure-failure
  Scenario: After a busy answer the search service is left alone for a minute
    Given place search is switched on and the search service answers that it is busy
    And Marco has searched for the place "Gorges du Verdon"
    When Marco searches for the place "Lagos"
    Then the planner says the place search isn't answering
    And the search service saw one request

  @US-29 @driving_port @error @edge
  Scenario: A name shorter than two letters is refused before anything is sent
    Given place search is switched on and answers "Gorges du Verdon" with one place
    When Marco searches for the place "G"
    Then the planner refuses the search and says the name is too short
    And the search service has seen no request

  @US-29 @driving_port @edge
  Scenario: Switching place search off removes it from the Add menu
    Given place search is switched off
    When Marco opens the map settings
    Then the map settings say place search is not offered

  @US-29 @driving_port @error @edge
  Scenario: A search is answered as not available when place search is switched off
    Given place search is switched off
    When Marco searches for the place "Gorges du Verdon"
    Then the planner says the place search isn't answering

  @US-29 @driving_port @edge
  Scenario: Leaving the search address empty means the usual address, not off
    Given place search is switched on with its address left empty
    When Marco opens the map settings
    Then the map settings say place search is offered

  @US-29 @US-28 @driving_port @real-io @adapter-integration @edge
  Scenario: A result outside the road map joins the trip as a kept, warned place
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And place search is switched on and answers "Lagos" with a place in Portugal and a place in Nigeria
    And Giulia is building "Assietta weekend"
    And Giulia has searched for the place "Lagos"
    When Giulia adds the one in Portugal
    Then the place "Lagos" is kept and is outside the road map

  # ===================== US-30 Rebuild progress, result, and the old map back =====================

  @US-30 @ui
  Scenario: Progress shows the step the rebuild is in
    Given a rebuild adding Portugal has started
    When Marco opens "Road map"
    Then he sees which step it is in (Waiting, "Checking the Pi's disk and memory", Downloading, Building or "Switching to the new map")
    And the loaded regions and map date are still those of the served map

  @US-30 @ui @edge
  Scenario: During the download the old map keeps planning
    Given the rebuild is downloading
    When Marco plans "Alpi Occidentali giugno 2027"
    Then the route is planned on the old map as usual

  @US-30 @ui @edge
  Scenario: During the build planning is disabled and the page says until when
    Given the rebuild is building
    When Marco opens "Assietta weekend" on Build the trip
    Then "Plan the route" is disabled with the line "The road map is being rebuilt; planning is back at about 22:20."
    And the trip and the exports of earlier routes stay readable

  @US-30 @ui
  Scenario: A successful rebuild shows the new regions and date everywhere
    Given the rebuild ended well
    When Marco opens Build the trip
    Then "Roads loaded for" names the new regions and "Map data" the new date
    And the "Road map" screen says the rebuild is done

  @US-30 @ui @error
  Scenario: A failed rebuild brings the old map back and says why
    Given the Pi has 18 GB of free disk and the rebuild needs 25 GB
    When Marco opens "Road map"
    Then it says the rebuild failed, why, in plain words, and that the change is kept
    And the earlier map, its regions and its date are served, and planning works

  @US-30 @ui @edge
  Scenario: A planned rebuild starts at its time and the result is there next morning
    Given Marco planned a rebuild for 02:00 and closed the page
    When he opens "Road map" on his phone at 08:00
    Then it shows the result of the rebuild that began at 02:00 and not before

  @US-30 @ui @error @edge
  Scenario: A rebuild interrupted by a power cut ends with the old map served
    Given the rebuild was building when the Pi lost power and the Pi has restarted
    When Marco opens "Road map"
    Then the earlier map is served again and the result says the rebuild was interrupted, with the change kept
    And if the switch to the new map had already happened, the result says the rebuild is done and the new regions are shown

  @US-30 @driving_port @real-io @adapter-integration
  Scenario Outline: The planner shows the step the helper has reached
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the helper has started a rebuild adding Portugal and is <step>
    When Marco asks the planner what road map it serves
    Then the change is running and its step is "<step>"
    And the regions served are still the eight

    Examples:
      | step         |
      | checking     |
      | downloading  |
      | building     |
      | switching    |

  @US-30 @driving_port @real-io @adapter-integration @edge
  Scenario Outline: Planning is paused from the build until the switch ends, and the planner says when it is back
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And today is 29 November 2026 at 03:30 UTC
    And the helper has started a rebuild adding Portugal and is <step>
    And the rebuild step began at 03:10 UTC
    When Marco asks the planner what road map it serves
    Then planning is <state>

    Examples:
      | step         | state                                          |
      | downloading  | not paused                                     |
      | building     | paused, back about 41 minutes after 03:10      |
      | switching    | paused, back about 41 minutes after 03:10      |

  @US-30 @driving_port @real-io @adapter-integration @error
  Scenario: A rebuild that stopped for lack of space says so, with the numbers, and the served map is untouched
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And a rebuild adding Portugal ended because the disk had 18 GB free and needed 25 GB
    When Marco asks the planner what road map it serves
    Then the change has failed and says not enough space on the disk, 18 GB free and 25 GB needed
    And the change is kept
    And the regions served are still the eight and the map data is still dated 27 November 2026

  @US-30 @driving_port @real-io @adapter-integration @error
  Scenario Outline: Every way a rebuild can fail is told in plain words, not as a code
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And a rebuild adding Portugal ended because <reason>
    When Marco asks the planner what road map it serves
    Then the change has failed and the words shown hold no code name

    Examples:
      | reason                                                  |
      | a deploy kept the Pi busy for half an hour              |
      | a map was already built that day                        |
      | the disk was too small                                  |
      | the memory was too small                                |
      | the road service of the Pi did not answer               |
      | a download failed                                       |
      | a region's border file was not found                    |
      | the regions could not be merged                         |
      | the map could not be built                              |
      | the Pi ran out of memory building the map               |
      | the road rules could not be applied                     |
      | the new map could not be put in place                   |
      | the new map did not start                               |
      | the Pi lost power                                       |

  @US-30 @driving_port @real-io @adapter-integration
  Scenario: A rebuild that ended well shows the new regions and date once the new map is served
    Given the Pi holds the maps of 1 November and 27 November, each with its regions
    And the Pi reports its map data is of 27 November
    And a rebuild adding Portugal ended well, making the map of 29 November
    And the Pi now serves the map of 29 November, whose regions are the eight and Portugal
    When Marco asks the planner what road map it serves
    Then the planner names the nine regions and the map date of the map of 29 November
    And the change is done

  # ===================== US-31 Start the rebuild now or at a time, cancel before it starts =====================

  @US-31 @ui
  Scenario: Marco picks now or a start time
    Given a pending change adds Portugal
    When he chooses "Rebuild now"
    Then the rebuild is waiting to start within a minute

  @US-31 @ui
  Scenario: Marco picks a start time
    Given a pending change adds Portugal
    When he chooses tonight 02:00
    Then the screen says "Rebuild planned for tonight 02:00"

  @US-31 @ui @edge
  Scenario: A planned rebuild can be cancelled until it starts
    Given a rebuild is planned for tonight 02:00
    When Marco cancels it at 22:00
    Then nothing is pending and the loaded regions and map date are unchanged

  @US-31 @ui @edge @error
  Scenario: A rebuild cannot be cancelled once it has started
    Given a rebuild has just started at 02:00
    When Marco presses "Cancel" at 02:01
    Then the screen says it has already started and the rebuild goes on

  @US-31 @ui @edge @error
  Scenario: Refresh map data is the same workflow
    Given the road map has the eight regions and Marco is on the "Road map" screen
    When he presses "Refresh map data" with the same regions
    Then the screen shows its size and time and offers "Rebuild now" or a start time

  @US-31 @ui @edge @error
  Scenario: While a change is pending or running a second change is refused
    Given a refresh of the map data is pending
    When Marco tries to add another region
    Then the second change is refused until the first is applied or cancelled

  @US-31 @ui @edge @error
  Scenario: One rebuild a day, counted by the kept map, with the next time shown
    Given a rebuild ended well on 27 November 2026 UTC and Marco is in Milan
    When he tries to start another the same UTC day
    Then the screen refuses it and says the next rebuild can start from 01:00 on 28 November
    And a rebuild that failed before the switch to the new map leaves no map that day, so it does not use the day up
    And a rebuild that failed after the switch keeps its map and does use the day up

  @US-31 @ui @error
  Scenario: Without the helper the screen says rebuilds are not set up
    Given the helper is not installed on the Pi
    When Marco opens "Road map" and tries to apply a change
    Then the screen says rebuilds are not set up on the Pi and refuses the change
    And the loaded regions and the page's other functions are unchanged

  @US-31 @driving_port @edge
  Scenario: Refresh map data asks for the same regions and shows the same cost
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When the owner asks what refreshing the map data would cost
    Then the summary says 6.4 GB to download, planning paused about 38 minutes and the rebuild about 55 minutes
    And the summary adds and removes no region

  @US-31 @driving_port @error
  Scenario: Only one change is pending at a time
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the owner has planned the change adding Portugal
    When the owner plans the change adding Utah
    Then the planner refuses it, because a change is already pending
    And the pending change still adds Portugal only

  @US-31 @driving_port @error @edge
  Scenario: A planned change cannot be cancelled once the helper has taken it
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the owner has planned the change adding Portugal for tonight at 02:00
    And the helper has taken it
    When the owner cancels it
    Then the planner refuses saying the rebuild has already started

  @US-31 @driving_port @error
  Scenario: A rebuild is refused on a day that already has a map, with the next day and time it may run
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And today is 27 November 2026 at 21:00 UTC
    When the owner plans the change adding Portugal to start now
    Then the planner refuses it, because a map was built today
    And it names 28 November 2026 as the next day a rebuild may run

  @US-31 @driving_port @error @edge
  Scenario: A new map left behind by a failed switch uses the day up
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And a new map of 28 November was left behind by a switch that failed
    And today is 28 November 2026 at 21:00 UTC
    When the owner plans the change adding Portugal to start now
    Then the planner refuses it, because a map was built today
    And it names 29 November 2026 as the next day a rebuild may run

  @US-31 @driving_port @edge
  Scenario: A rebuild that failed before the switch leaves no map, so the day is not used up
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And today is 28 November 2026 at 21:00 UTC
    And a rebuild adding Portugal ended because the disk was too small
    When the owner plans the change adding Portugal to start now
    Then the planner keeps it pending

  @US-31 @driving_port @error @edge
  Scenario Outline: A start time must be between two minutes and fourteen days ahead
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    When the owner plans the change adding Portugal to start <ahead> from now
    Then the planner <outcome>

    Examples:
      | ahead              | outcome                                       |
      | 1 minute           | refuses it, because the start time is not valid |
      | 3 minutes          | keeps it pending                              |
      | 14 days            | keeps it pending                              |
      | 15 days            | refuses it, because the start time is not valid |

  @US-31 @driving_port @real-io @adapter-integration @error
  Scenario: Without the helper the planner says rebuilds are not set up and refuses the change
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the helper has never run on the Pi
    When the owner plans the change adding Portugal
    Then the planner refuses it, because rebuilds are not set up on the Pi

  @US-31 @driving_port @real-io @adapter-integration @error @edge
  Scenario Outline: The helper counts as set up while it looked less than five minutes ago
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the helper last looked <ago> minutes ago
    When the owner plans the change adding Portugal
    Then the planner <outcome>

    Examples:
      | ago | outcome                                                    |
      | 4   | keeps it pending                                           |
      | 6   | refuses it, because rebuilds are not set up on the Pi      |

  @US-31 @driving_port @real-io @adapter-integration @error @edge
  Scenario: A waiting change that the helper has not looked at for minutes says rebuilds are not set up
    Given the road map was rebuilt from the app and the served map holds the eight regions, with map data of 27 November 2026
    And the owner has planned the change adding Portugal
    And the helper last looked 10 minutes ago
    When Marco asks the planner what road map it serves
    Then the planner says rebuilds are not set up on the Pi

  # ===================== The helper and the refresh script on the Pi (offline; US-27, US-30, US-31; D303, D304, D314) =====================

  @US-31 @script @offline
  Scenario: The helper is installed once and runs every minute
    Given a Pi that runs no jobs of its own
    When the helper is installed
    Then the Pi runs the road-map helper every minute
    And nothing in it names a host, a user or an address

  @US-31 @script @offline @edge
  Scenario: A Pi whose app folder name has a space runs the helper too
    Given a Pi whose app folder has a space in its name and which runs no jobs of its own
    When the helper is installed
    Then the Pi runs the road-map helper every minute, whatever the folder's name

  @US-31 @script @offline @edge
  Scenario: Installing again replaces the helper's own job and keeps the Pi's other jobs as they are
    Given a Pi with a nightly backup and a note, and an older road-map helper
    When the helper is installed
    Then the Pi runs the road-map helper every minute and keeps its backup and its note exactly

  @US-31 @script @offline @edge
  Scenario: The helper is added beside the Pi's other jobs, which are kept exactly
    Given a Pi with a nightly backup and a note
    When the helper is installed
    Then the Pi runs the road-map helper every minute and keeps its backup and its note exactly
    And the Pi's earlier jobs are saved before the change

  @US-31 @script @offline @edge
  Scenario: Uninstalling removes only the helper's job
    Given a Pi with a nightly backup and the road-map helper
    When the helper is uninstalled
    Then the Pi keeps its backup and no longer runs the road-map helper

  @US-31 @script @offline @error @infrastructure-failure
  Scenario: A Pi whose jobs cannot be read is left alone
    Given a Pi with a nightly backup whose jobs cannot be read for a reason other than having none
    When the helper is installed
    Then the Pi's jobs are exactly as they were
    And the helper says it did not install

  @US-31 @script @offline @edge
  Scenario Outline: The helper says whether it is installed
    Given <jobs>
    When the helper is asked whether it is installed
    Then the helper answers that it is <state>

    Examples:
      | jobs                                              | state         |
      | a Pi with a nightly backup and the road-map helper | installed     |
      | a Pi with a nightly backup and a note             | not installed |

  @US-31 @script @offline @error @infrastructure-failure
  Scenario: A Pi that cannot take the helper does not fail the deploy
    Given a Pi whose jobs cannot be changed
    When a release is deployed
    Then the deploy ends well with one warning that the helper was not installed
    And the release is recorded

  @US-31 @script @offline @edge
  Scenario: Removing the app from the Pi stops the helper first
    Given a Pi with a nightly backup and the road-map helper
    When the owner asks to purge the Pi's data
    Then the helper stops running before anything else is removed

  @US-30 @US-31 @script @offline
  Scenario: A request is taken at its time and the rebuild runs on the regions it names
    Given a Pi serving the map of 1 November and a request adding Portugal whose start time has come
    When the helper runs
    Then the rebuild ran on the regions of the request, not on the old list of eight
    And the request was taken and the rebuild ended well

  @US-31 @script @offline @edge
  Scenario: A request is not started before its time
    Given a Pi serving the map of 1 November and a request adding Portugal to start in 3 hours
    When the helper runs
    Then nothing was started and the request is still waiting

  @US-30 @script @offline @error
  Scenario Outline: A request that is not exactly what the planner writes is refused and nothing runs
    Given a Pi serving the map of 1 November and a request with <fault>
    When the helper runs
    Then nothing was started
    And the result says the request was not valid

    Examples:
      | fault                                              |
      | a region address on another host                   |
      | a region address that belongs to another region    |
      | a region name that goes up a level                 |
      | a size that is not a number                        |
      | forty-one regions                                  |
      | a start time that is not a number                  |
      | a command hidden in a region line                  |
      | a link in place of the request                     |

  @US-30 @script @offline @error @security
  Scenario: The helper cannot reach the internet or the served map
    Given a Pi serving the map of 1 November and a request adding Portugal whose start time has come
    When the helper runs
    Then the helper acted as an ordinary user with no extra rights, and could not reach the internet or the served map

  @US-31 @script @offline @edge
  Scenario: A request cancelled just before the helper looks is not started
    Given a Pi serving the map of 1 November and a request that the owner cancelled a moment ago
    When the helper runs
    Then nothing was started

  @US-30 @script @offline @edge
  Scenario: A rebuild refused because a deploy is running is tried again the next minute
    Given a Pi serving the map of 1 November and a request adding Portugal whose start time has come
    And a deploy is running on the Pi
    When the helper runs
    Then the request is waiting again and no result was written

  @US-30 @script @offline @edge
  Scenario: Two helpers at the same minute: the second leaves at once
    Given a Pi serving the map of 1 November and a rebuild that the helper is still running
    When the helper runs
    Then the second run ends at once and touches nothing

  @US-30 @script @offline @error @infrastructure-failure
  Scenario: A rebuild the Pi lost before the switch is recorded as interrupted and the old map serves
    Given a Pi serving the map of 1 November that lost power during a rebuild making the map of 1 February 2027
    When the helper runs
    Then the result says the rebuild was interrupted
    And the Pi serves the map of 1 November again

  @US-30 @script @offline @edge
  Scenario: A rebuild the Pi lost after the switch is recorded as done
    Given a Pi serving the map of 1 February 2027 that lost power right after a rebuild made it
    When the helper runs
    Then the result says the rebuild ended well

  @US-30 @script @offline @edge
  Scenario: A rebuild the Pi lost is not touched while a deploy is running
    Given a Pi serving the map of 1 November that lost power during a rebuild making the map of 1 February 2027
    And a deploy is running on the Pi
    When the helper runs
    Then nothing was started and no result was written

  @US-30 @script @offline @error
  Scenario: The rebuild refuses for lack of disk with the numbers, and the helper keeps them
    Given a Pi serving the map of 1 November and a request adding Portugal whose start time has come
    And the Pi has 12 GB of free disk
    When the helper runs
    Then the result says the rebuild failed for lack of space, with the free and the needed GB

  @US-27 @script @offline
  Scenario: A rebuild from a list of regions downloads each region on its own
    Given a Pi serving the map of 1 November and a list of regions with two that share a last name
    When the rebuild runs on that list
    Then each region is downloaded on its own
    And the eight regions of the old list were not downloaded

  @US-27 @script @offline @error
  Scenario: A region whose border file cannot be fetched stops the rebuild before anything is stopped
    Given a Pi serving the map of 1 November and a list of regions where the border file of Portugal is not found
    When the rebuild runs on that list
    Then the rebuild refuses, naming Portugal
    And the road service was never stopped and the served map is unchanged

  @US-30 @script @offline
  Scenario: The rebuild reports its steps in order
    Given a Pi serving the map of 1 November and a list of regions
    When the rebuild runs with progress reporting on
    Then the steps reported were checking, downloading, building and switching, in that order

  @US-30 @script @offline @edge
  Scenario: The rebuild says nothing about its steps when not asked
    Given a Pi serving the map of 1 November and a list of regions
    When the rebuild runs with progress reporting off
    Then no step was reported

  @US-27 @script @offline
  Scenario: The rebuild builds the list of the map's regions itself, and it travels with the new map
    Given a Pi serving the map of 1 November and a list of regions
    When the rebuild runs on that list
    Then the new map holds the list of its regions, with their names and parents as in the list, and the region borders
    And the old map is kept for rollback

  @US-27 @script @offline @edge
  Scenario: The map's integrity check covers its regions and borders too
    Given a Pi serving the map of 1 November and a list of regions
    When the rebuild runs on that list
    Then the integrity check of the new map covers its tiles, its regions and its borders

  @US-27 @script @offline @edge
  Scenario: Seeding a map again still recognises the same tiles after the integrity check grew
    Given a Pi whose seeded map has an integrity check that also covers its regions and borders
    When the map is seeded again from the same source
    Then the seed ends saying the map is unchanged

  @US-27 @script @offline @error
  Scenario Outline: The disk the rebuild needs grows with the download
    Given a Pi serving the map of 1 November and a list of regions totalling <download>
    And the Pi has <free> of free disk
    When the rebuild runs on that list
    Then the rebuild <outcome>

    Examples:
      | download | free  | outcome                                    |
      | 6.4 GB   | 26 GB | starts                                     |
      | 8 GB     | 28 GB | refuses, saying it needs 31 GB             |
      | 8 GB     | 32 GB | starts                                     |

  @US-30 @script @offline @edge @error
  Scenario: A rebuild refused because a deploy is running says so, and reports no failure
    Given a Pi serving the map of 1 November and a list of regions
    And a deploy is running on the Pi
    When the rebuild runs on that list
    Then the rebuild stops saying a deploy is running, which is not a failure
    And no failure is reported

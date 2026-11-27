// Slice 12c the planner knows its map (US-27 to US-31): the @ui scenarios of
// tests/acceptance/overland_route_planner_mvp/slice-12c-the-planner-knows-its-map.feature, one test per scenario, named
// after it (DISTILL D312). Every test is `test.fixme` until the DELIVER step that builds its behaviour turns it into
// `test` and writes its body (the Gherkin lines are kept in each body as the plan); CI job 7 skips them, so it stays green.
//
// Runs in CI job 7 on chromium (Desktop Chrome; 1440 x 900 set per test with `page.setViewportSize`) and
// webkit-iphone14 (390 px) against the packaged planner on PLANNER_URL, which plans on the offline road map, as
// trip-workflow.spec.ts (slice 12b). A test meant for one width skips itself on the other project.
//
// Fixtures the DELIVER bodies need (the steps' "the served map has the eight regions ..." and "the helper ..."):
//  - a fixture volume: the planner of CI job 7 starts with ROAD_MAP_DIR on a tileset folder holding `road-map.json` (the
//    eight regions of tests/acceptance/overland_route_planner_mvp/fixtures/road-map/) and their `.poly` outlines,
//    ROAD_MAP_SERVED_TILESET naming it, and ROAD_MAP_CHANGES_DIR on an empty folder; the files the helper writes
//    (running.txt, progress.txt, result.txt) are written into that folder by the test itself, as the acceptance steps do;
//  - the two foreign services never come from the internet: GEOFABRIK_INDEX_URL and PLACE_SEARCH_URL point at small
//    local servers of the test run (fixtures/road-map/geofabrik-index-trimmed.json; a Nominatim answer for "Gorges du
//    Verdon", "Lagos" (Portugal and Nigeria) and "Zxqvbn" (nothing)), or the browser's own `page.route` answers the
//    planner's `/api/road-map/catalogue` and `/api/places/search` (policy waiver W4: read the real answer once, the
//    handler only fulfills it);
//  - "typed without pressing Search sends nothing" is read from the request log of that local server, never from a timer.
import {
  expect,
  test,
  type Locator,
  type Page,
  type TestInfo,
} from "@playwright/test";
import { serveTheBaseMap } from "./blankTile";

const AT_LAPTOP = { width: 1440, height: 900 };
const AT_PHONE = { width: 390, height: 844 };

// Referenced by the bodies DELIVER writes; kept so the widths are decided once.
void AT_LAPTOP;
void AT_PHONE;

// W4 without a race (as trip-workflow.spec.ts): the planner's real answer is read once now, changed, and every later GET
// matching `pattern` is fulfilled with that copy; the handler never fetches.
async function answerWith<T>(
  page: Page,
  pattern: RegExp,
  address: string,
  change: (real: T) => T,
): Promise<void> {
  const real = (await (await page.request.get(address)).json()) as T;
  const rewritten = change(real);
  await page.route(pattern, (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: rewritten })
      : route.continue(),
  );
}

interface Served {
  served: { known: boolean; regions: { name: string }[] };
}
interface Coverage {
  known: boolean;
  regions: string[];
  outside_item_ids: string[];
}

const tripList = (page: Page): Locator =>
  page.getByRole("list", { name: "Your trip" });

// The served map's regions, as the planner names them, joined with commas and "and" as the page does.
async function servedRegions(page: Page): Promise<string> {
  const { served } = (await (
    await page.request.get("/api/road-map")
  ).json()) as Served;
  const names = served.regions.map((region) => region.name);
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

async function newProject(
  page: Page,
  testInfo: TestInfo,
  label = "Spagna test",
): Promise<void> {
  const name = `${label} (${testInfo.project.name} ${Date.now()})`;
  await page.goto("/");
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "New project" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

async function addPlaceOnTheForm(
  page: Page,
  name: string,
  lat: string,
  lon: string,
): Promise<void> {
  const before = await tripList(page).getByRole("listitem").count();
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("button", { name: "Type coordinates" }).click();
  const form = page.getByRole("form", { name: "Type coordinates" });
  await form.getByLabel("Name").fill(name);
  await form.getByLabel("Latitude").fill(lat);
  await form.getByLabel("Longitude").fill(lon);
  await form.getByRole("button", { name: "Add" }).click();
  await expect(tripList(page).getByRole("listitem")).toHaveCount(before + 1);
}

// A short trail on the Algarve (Portugal): its entry and exit are both outside the eight regions.
const ALGARVE_GPX = `<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="slice-12c-test" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>algarve</name><trkseg>${[
  [37.1, -8.6],
  [37.12, -8.57],
  [37.14, -8.54],
  [37.16, -8.5],
]
  .map(([lat, lon]) => `<trkpt lat="${lat}" lon="${lon}"></trkpt>`)
  .join("")}</trkseg></trk></gpx>`;

// The row menu of a place: "Set as start" or "Set as end".
async function setFromTheRow(
  page: Page,
  place: string,
  choice: "Set as start" | "Set as end",
): Promise<void> {
  const row = tripList(page).getByRole("listitem").filter({ hasText: place });
  await row.getByRole("button", { name: `Actions for ${place}` }).click();
  await page.getByRole("button", { name: choice }).click();
}

const projectIdOf = (url: string): string =>
  decodeURIComponent(/#\/projects\/([^/]+)$/.exec(url)![1]);

// @US-27 @ui
test.fixme("The Road map screen shows what is loaded", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the road map was rebuilt from the app and the served map has the eight regions, with map data of 27 November 2026
  // When Marco opens "Road map" from the header beside the projects
  // Then he sees the eight regions by name and "Map data: 27 November 2026"
  // And no file, script or setting needs to be edited to change them
});

// @US-27 @ui @edge
test.fixme("Before the first rebuild from the app the screen says the regions are unknown", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the served map was built on 26 November 2026, before the app kept the regions of a map
  // When Marco opens "Road map"
  // Then he sees "Map coverage unknown" with the map date and no list of regions
  // And he is offered "Refresh map data" to build the same eight regions again
});

// @US-27 @ui
test.fixme("A region is added by searching the free list of regions by name", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the road map has the eight regions and Marco is on the "Road map" screen
  // When he searches "Utah" and adds the result
  // Then "Utah" is listed as "to be added" and the loaded regions are still the eight
  // And the screen says Utah is not linked by land to the other regions, as information only
});

// @US-27 @ui @edge
test.fixme("A region is removed as a pending change", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the loaded regions include Austria
  // When Marco removes Austria
  // Then Austria is listed as "to be removed" and is still loaded until a rebuild ends well
});

// @US-27 @ui
test.fixme("Size and time are shown before applying", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given Marco has added Portugal
  // Then the screen shows "Total download 6.8 GB", about 58 minutes in all and about 41 without planning
});

// @US-27 @ui @error
test.fixme("Too big is refused with the size", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given Marco has added Portugal
  // When he adds "North America" and the total goes above the limit of 8 GB
  // Then the screen refuses it, saying the size and the limit, and the pending change is unchanged
});

// @US-28 @ui
test("Build the trip shows the regions and the map date", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given after a rebuild from the app the served map has the eight regions, with map data of 27 November 2026
  const regions = await servedRegions(page);
  // When Marco opens "Alpi Occidentali giugno 2027" on Build the trip
  await newProject(page, testInfo, "Alpi Occidentali giugno 2027");
  // Then he sees "Roads loaded for" with those eight names and "Map data: 27 November 2026"
  const panel = page.getByRole("region", { name: "Build the trip" });
  await expect(panel).toContainText(`Roads loaded for: ${regions}`);
  await expect(panel).toContainText("Map data: 27 November 2026");
  // And neither is inside "Details"
  // (a <details> may exist on the page, such as the map's compact credit on a phone: none holds these lines)
  await expect(
    page.locator("details", { hasText: "Roads loaded for" }),
  ).toHaveCount(0);
  await expect(
    page.locator("details", { hasText: "Map data: 27 November" }),
  ).toHaveCount(0);
  // And on a 390 px wide iPhone both are shown in full width text with no horizontal scroll
  await page.setViewportSize(AT_PHONE);
  await expect(panel).toContainText(`Roads loaded for: ${regions}`);
  await expect(panel).toContainText("Map data: 27 November 2026");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

// @US-28 @ui @edge
test("A trail outside the map is warned at add time and on its row, and kept", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given Marco is building "Spagna test"
  const regions = await servedRegions(page);
  await newProject(page, testInfo);
  await expect(page.getByText("Roads loaded for:")).toBeVisible();
  // When he uploads "algarve.gpx", a trail in Portugal
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("button", { name: "Upload GPX trails" }).click();
  await (
    await chooser
  ).setFiles({
    name: "algarve.gpx",
    mimeType: "application/gpx+xml",
    buffer: Buffer.from(ALGARVE_GPX),
  });
  // Then the page says "algarve" is outside the planner's road map and names the regions loaded
  await expect(page.getByRole("alert")).toContainText(
    `algarve is outside the planner's road map (${regions})`,
  );
  // And the trail stays in the list with an "Outside road map" tag on its row
  const row = tripList(page)
    .getByRole("listitem")
    .filter({ hasText: "algarve" });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Outside road map");
});

// @US-28 @ui @edge
test("A place outside the map is warned when added by a click on the map", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given Marco is building "Spagna test"
  const regions = await servedRegions(page);
  await newProject(page, testInfo);
  await expect(page.getByText("Roads loaded for:")).toBeVisible();
  // the map's own hook (?e2e=1) puts Morocco under the middle of the map, so that the click lands there
  await page.goto(page.url().replace("/#/", "/?e2e=1#/"));
  const map = page.getByRole("region", { name: "Map of the trip" });
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(
    () =>
      !!(window as unknown as { __overlandRunMap?: unknown }).__overlandRunMap,
  );
  await page.evaluate(() => {
    const drawn = (
      window as unknown as {
        __overlandRunMap: {
          jumpTo: (view: { center: number[]; zoom: number }) => void;
        };
      }
    ).__overlandRunMap;
    drawn.jumpTo({ center: [-5.2636, 35.1688], zoom: 9 });
  });
  // When he adds "Chefchaouen" in Morocco by a click on the map
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("button", { name: "Click on the map" }).click();
  await expect(
    map.getByRole("button", { name: "Click on map to add" }),
  ).toHaveAttribute("aria-pressed", "true");
  const frame = (await map.locator("canvas.maplibregl-canvas").boundingBox())!;
  await page.mouse.click(frame.x + frame.width / 2, frame.y + frame.height / 2);
  const form = page.getByRole("form", { name: "Add a place here" });
  await form.getByLabel("Name").fill("Chefchaouen");
  await form.getByRole("button", { name: "Add" }).click();
  // Then it is kept and shows the warning when added and the tag on its row
  await expect(page.getByRole("alert")).toContainText(
    `Chefchaouen is outside the planner's road map (${regions})`,
  );
  const row = tripList(page)
    .getByRole("listitem")
    .filter({ hasText: "Chefchaouen" });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Outside road map");
});

// @US-28 @ui @edge
test("A place outside the map is warned when added by typed coordinates", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given Marco is building "Spagna test"
  const regions = await servedRegions(page);
  await newProject(page, testInfo);
  await expect(page.getByText("Roads loaded for:")).toBeVisible();
  // When he adds "Lagos" in Portugal by typed coordinates
  await addPlaceOnTheForm(page, "Lagos", "37.1028", "-8.6742");
  // Then it is kept and shows the warning when added and the tag on its row
  await expect(page.getByRole("alert")).toContainText(
    `Lagos is outside the planner's road map (${regions})`,
  );
  const row = tripList(page).getByRole("listitem").filter({ hasText: "Lagos" });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Outside road map");
  // the warning is shown once: dismissed, it does not come back when another place is added
  await page.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await addPlaceOnTheForm(page, "Cadaques", "42.2889", "3.2776");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(row).toContainText("Outside road map");
});

// @US-28 @ui
test("A place inside the map shows no warning", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given the loaded regions include Spain, as after a rebuild from the app
  await newProject(page, testInfo);
  await expect(page.getByText("Roads loaded for:")).toContainText("Spain");
  // When Marco adds "Cadaques" at 42.2889, 3.2776
  await addPlaceOnTheForm(page, "Cadaques", "42.2889", "3.2776");
  // Then no warning is shown, at add time or on its row
  await expect(page.getByText("Roads loaded for:")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByText("Outside road map")).toHaveCount(0);
});

// @US-28 @ui @error
test("Planning is not blocked by an outside item and says why it fails", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given "Spagna test" holds "Torino" as Start and End and the Moroccan place "Chefchaouen"
  const regions = await servedRegions(page);
  await newProject(page, testInfo);
  await expect(page.getByText("Roads loaded for:")).toBeVisible();
  await addPlaceOnTheForm(page, "Torino", "45.0703", "7.6869");
  await setFromTheRow(page, "Torino", "Set as start");
  await setFromTheRow(page, "Torino", "Set as end");
  await addPlaceOnTheForm(page, "Chefchaouen", "35.1688", "-5.2636");
  // When Marco presses "Plan the route"
  const plan = page.getByRole("button", { name: "Plan the route" });
  await expect(plan).toBeEnabled();
  await plan.click();
  // Then the planner's own words are shown for the run that couldn't plan
  // (the offline planner of CI plans anywhere as an estimate, so its answer for that run is read once and rewritten as the
  // refusal of a planner whose roads end at the regions, W4: the handlers only fulfill)
  await expect(
    page.getByRole("region", { name: "Your route", exact: true }),
  ).toBeVisible({ timeout: 90_000 });
  const id = encodeURIComponent(projectIdOf(page.url()));
  const line =
    "Plan run #1 failed: 'Chefchaouen' cannot be connected to any other stop";
  await answerWith<{ id: string; status: string }[]>(
    page,
    /\/api\/projects\/[^/]+\/plan-runs(\?.*)?$/,
    `/api/projects/${id}/plan-runs`,
    (real) => real.map((run) => ({ ...run, status: "failed" })),
  );
  const runs = (await (
    await page.request.get(`/api/projects/${id}/plan-runs`)
  ).json()) as { id: string }[];
  await answerWith<Record<string, unknown>>(
    page,
    /\/api\/plan-runs\/[^/]+$/,
    `/api/plan-runs/${runs[0].id}`,
    (real) => ({
      ...real,
      status: "failed",
      failure_reason: "unreachable",
      stops: [],
      totals: null,
      report: null,
      estimate: false,
      messages: [line],
    }),
  );
  await page.reload();
  await expect(page.getByText(line)).toBeVisible();
  // And the page names the regions with roads, as the row warning already did
  await expect(
    page.getByText(`The planner's road map covers ${regions}`),
  ).toBeVisible();
});

// @US-28 @ui @error @edge
test("Without knowledge of the loaded map the page does not invent warnings", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given the served map was built on 26 November 2026, before the app kept its regions, or the page cannot read them
  await newProject(page, testInfo);
  await expect(page.getByText("Roads loaded for:")).toBeVisible();
  await answerWith<Coverage>(
    page,
    /\/api\/projects\/[^/]+\/coverage$/,
    `/api/projects/${encodeURIComponent(projectIdOf(page.url()))}/coverage`,
    (real) => ({ ...real, known: false, regions: [], outside_item_ids: [] }),
  );
  // When Marco adds "Chefchaouen"
  await addPlaceOnTheForm(page, "Chefchaouen", "35.1688", "-5.2636");
  // Then the page says "Map coverage unknown" with the map date and shows no "Roads loaded for" list
  await expect(page.getByText("Map coverage unknown")).toBeVisible();
  await expect(page.getByText("Map data: 27 November 2026")).toBeVisible();
  await expect(page.getByText("Roads loaded for")).toHaveCount(0);
  // And it shows no outside-the-map warning or tag for any item
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByText("Outside road map")).toHaveCount(0);
});

// @US-28 @ui @edge
test("Stops in areas not linked by land are warned on Build the trip", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given after a rebuild from the app the loaded regions are the eight above and Utah, which is not linked by land to them
  const regions = (
    (await (await page.request.get("/api/road-map")).json()) as Served
  ).served.regions.map((region) => region.name);
  await newProject(page, testInfo);
  await expect(page.getByText("Roads loaded for:")).toBeVisible();
  // When Marco's trip holds "Torino" as Start and the place "Moab" in Utah
  await addPlaceOnTheForm(page, "Torino", "45.0703", "7.6869");
  await setFromTheRow(page, "Torino", "Set as start");
  await setFromTheRow(page, "Torino", "Set as end");
  await expect(page.getByText(/not linked by land/)).toHaveCount(0);
  await answerWith<Coverage & { groups: unknown[] }>(
    page,
    /\/api\/projects\/[^/]+\/coverage$/,
    `/api/projects/${encodeURIComponent(projectIdOf(page.url()))}/coverage`,
    (real) => ({
      ...real,
      known: true,
      regions: [...regions, "Utah"],
      outside_item_ids: [],
      groups: [
        { regions, item_ids: ["torino"] },
        { regions: ["Utah"], item_ids: ["moab"] },
      ],
    }),
  );
  await addPlaceOnTheForm(page, "Moab", "38.5733", "-109.5498");
  // Then Build the trip says these stops are in areas not linked by land, so a trip between them would need a ferry
  const panel = page.getByRole("region", { name: "Build the trip" });
  await expect(panel).toContainText("not linked by land");
  await expect(panel).toContainText("would need a ferry");
  await expect(panel).toContainText("Utah");
  // And "Plan the route" stays available
  await expect(
    panel.getByRole("button", { name: "Plan the route" }),
  ).toBeEnabled();
});

// The local stand-in for Nominatim (.github/scripts/fake-place-search.py): the planner's PLACE_SEARCH_URL points at it and
// its request log says what was sent. Words that carry a stamp are asked once only, so the planner's 24 h memory of
// answers (13-14) never hides a request from the log.
const FAKE_SEARCH =
  process.env.FAKE_PLACE_SEARCH_URL ?? "http://127.0.0.1:8765";
const UNAVAILABLE =
  "The place search isn't answering. Try again in a minute, or add the place another way.";

const stamped = (words: string, testInfo: TestInfo): string =>
  `${words} ${testInfo.project.name}-${Date.now()}`;

async function sentWords(page: Page): Promise<string[]> {
  return (await (
    await page.request.get(`${FAKE_SEARCH}/__requests`)
  ).json()) as string[];
}

async function openTheSearch(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("button", { name: "Search for a place" }).click();
  const form = page.getByRole("form", { name: "Search for a place" });
  await expect(form).toBeVisible();
  return form;
}

async function searchFor(form: Locator, words: string): Promise<void> {
  await form.getByLabel("Place name").fill(words);
  await form.getByRole("button", { name: "Search", exact: true }).click();
}

const FINE_PRINT =
  "Only the words you type are sent, from your home connection, to OpenStreetMap's public place search (Nominatim). Your trip and files stay at home. Don't type personal details. Search © OpenStreetMap contributors.";

// @US-29 @ui
test("A place is found by name and joins the trip", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given Marco is building "Assietta weekend" and has chosen "Search for a place" in "Add"
  await newProject(page, testInfo, "Assietta weekend");
  await expect(page.getByText("Roads loaded for:")).toBeVisible();
  const form = await openTheSearch(page);
  // When he types "Gorges du Verdon" and presses "Search"
  await searchFor(form, "Gorges du Verdon");
  // Then he sees results with their region names
  const result = form.getByRole("listitem").filter({
    hasText: "Gorges du Verdon, Provence-Alpes-Côte d'Azur, France",
  });
  await expect(result).toHaveCount(1);
  // And after he picks it, it is in the list as a place, with no warning (the map covers it); the form stays open
  await result.getByRole("button", { name: "Add" }).click();
  await expect(
    tripList(page)
      .getByRole("listitem")
      .filter({ hasText: "Gorges du Verdon" }),
  ).toHaveCount(1);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(form).toBeVisible();
});

// @US-29 @ui @edge
test("Nothing is sent until Marco presses Search, and the screen says what leaves the house", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given the search form of "Add" is open
  await newProject(page, testInfo, "Assietta weekend");
  const form = await openTheSearch(page);
  // When Marco types "Gorges du Verdon" without pressing Search
  const words = stamped("Gorges du Verdon", testInfo);
  await form.getByLabel("Place name").pressSequentially(words);
  await expect(form.getByLabel("Place name")).toHaveValue(words);
  // Then no search is made (read from the request log of the local search server)
  expect((await sentWords(page)).filter((q) => q === words)).toEqual([]);
  // And the form says what leaves the house
  await expect(form).toContainText(FINE_PRINT);
  // Enter is the same as the button: now one search is made
  await form.getByLabel("Place name").press("Enter");
  await expect(form.getByRole("listitem")).toHaveCount(1);
  expect((await sentWords(page)).filter((q) => q === words)).toEqual([words]);
});

// @US-29 @ui @error
test("No result gives a clear message", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given the search form is open
  await newProject(page, testInfo, "Assietta weekend");
  const form = await openTheSearch(page);
  // When Marco searches "Zxqvbn" and nothing is found
  await searchFor(form, "Zxqvbn");
  // Then he reads that nothing was found with a hint to add the place on the map
  await expect(form).toContainText(
    "No place found for 'Zxqvbn'. Try another spelling or add it by clicking on the map.",
  );
  // And the trip is unchanged
  await expect(tripList(page).getByRole("listitem")).toHaveCount(0);
});

// @US-29 @ui @error @infrastructure-failure
test("An unreachable or busy search service leaves the trip unchanged", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given the search service does not answer, or answers that it is busy
  // (W4: the handler only fulfils with the planner's 503 envelope, or aborts; it never fetches)
  await newProject(page, testInfo, "Assietta weekend");
  let mode: "busy" | "unreachable" = "busy";
  await page.route(/\/api\/places\/search/, (route) =>
    mode === "busy"
      ? route.fulfill({
          status: 503,
          json: {
            code: "place_search_unavailable",
            message: "Place search is not available right now",
          },
        })
      : route.abort(),
  );
  const form = await openTheSearch(page);
  for (mode of ["busy", "unreachable"] as const) {
    // When Marco searches "Gorges du Verdon"
    await searchFor(form, "Gorges du Verdon");
    // Then he reads that the place search isn't answering and to try again later or add the place another way
    await expect(form.getByRole("alert")).toHaveText(UNAVAILABLE);
    await expect(form.getByRole("listitem")).toHaveCount(0);
  }
  // And the trip is unchanged, and the other ways to add still work
  await expect(tripList(page).getByRole("listitem")).toHaveCount(0);
  await addPlaceOnTheForm(page, "Lago del Moncenisio", "45.2280", "6.9420");
  await expect(tripList(page).getByRole("listitem")).toHaveCount(1);
});

// @US-29 @ui @edge
test("A result outside the road map is added with the warning", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given the loaded regions are the eight of the served map
  const regions = await servedRegions(page);
  await newProject(page, testInfo, "Assietta weekend");
  await expect(page.getByText("Roads loaded for:")).toBeVisible();
  const form = await openTheSearch(page);
  // When Marco searches "Lagos" and picks the result in Portugal
  await searchFor(form, "Lagos");
  const portugal = form
    .getByRole("listitem")
    .filter({ hasText: "Lagos, Algarve, Portugal" });
  await expect(portugal).toHaveCount(1);
  await portugal.getByRole("button", { name: "Add" }).click();
  // Then "Lagos" is in the list with the outside-the-map warning, at add time and as a tag on its row
  await expect(page.getByRole("alert")).toContainText(
    `Lagos is outside the planner's road map (${regions})`,
  );
  const row = tripList(page).getByRole("listitem").filter({ hasText: "Lagos" });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Outside road map");
});

// @US-29 @ui @edge
test("Pressing Search twice quickly sends one search", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  await newProject(page, testInfo, "Assietta weekend");
  const form = await openTheSearch(page);
  // Given Marco has typed "Gorges du Verdon"
  const words = stamped("Gorges du Verdon", testInfo);
  await form.getByLabel("Place name").fill(words);
  // When he presses "Search" twice within a second
  await form.getByRole("button", { name: "Search", exact: true }).dblclick();
  // Then one search is made and the results are shown once
  await expect(form.getByRole("listitem")).toHaveCount(1);
  expect((await sentWords(page)).filter((q) => q === words)).toEqual([words]);
});

// @US-29 @ui @phone @edge
test("On a phone the search form fits and opens in the page flow", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "webkit-iphone14", "the phone only");
  test.setTimeout(120_000);
  await page.setViewportSize(AT_PHONE);
  await serveTheBaseMap(page, testInfo);
  // Given Marco opens "Add" on his 390 px wide iPhone
  await newProject(page, testInfo, "Assietta weekend");
  const add = page.getByRole("button", { name: "Add", exact: true }).first(); // the menu's own, before any result
  // When he chooses "Search for a place"
  const form = await openTheSearch(page);
  await searchFor(form, "Gorges du Verdon");
  await expect(form.getByRole("listitem")).toHaveCount(1);
  // Then the form and results open under the heading bar in the page flow, not covering "Plan the route"
  const positions = await form.evaluate((node) => {
    const found: string[] = [];
    for (let at: Element | null = node; at; at = at.parentElement)
      found.push(getComputedStyle(at).position);
    return found;
  });
  expect(positions.filter((p) => p === "absolute" || p === "fixed")).toEqual(
    [],
  );
  const formBox = (await form.boundingBox())!;
  const addBox = (await add.boundingBox())!;
  expect(formBox.y).toBeGreaterThanOrEqual(addBox.y + addBox.height - 0.5);
  // "Plan the route" is pinned to the bottom of the screen: nothing of the form is above it in the stacking order, so
  // the button is still the element under its own centre
  const plan = page.getByRole("button", { name: "Plan the route" });
  await expect(plan).toBeVisible();
  expect(
    await plan.evaluate((node) => {
      const box = node.getBoundingClientRect();
      const top = document.elementFromPoint(
        box.x + box.width / 2,
        box.y + box.height / 2,
      );
      return top === node || node.contains(top);
    }),
    "the form does not cover Plan the route",
  ).toBe(true);
  // the form fits: no sideways scroll, and it ends inside the screen's width
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(formBox.x + formBox.width).toBeLessThanOrEqual(AT_PHONE.width + 0.5);
  // And every control is at least 44 px high and wide
  for (const control of await form.locator("button, input").all()) {
    const box = (await control.boundingBox())!;
    expect(box.height).toBeGreaterThanOrEqual(43.5);
    expect(box.width).toBeGreaterThanOrEqual(43.5);
  }
});

// @US-30 @ui
test.fixme("Progress shows the step the rebuild is in", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given a rebuild adding Portugal has started
  // When Marco opens "Road map"
  // Then he sees which step it is in (Waiting, "Checking the Pi's disk and memory", Downloading, Building or "Switching to the new map")
  // And the loaded regions and map date are still those of the served map
});

// @US-30 @ui @edge
test.fixme("During the download the old map keeps planning", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the rebuild is downloading
  // When Marco plans "Alpi Occidentali giugno 2027"
  // Then the route is planned on the old map as usual
});

// @US-30 @ui @edge
test.fixme("During the build planning is disabled and the page says until when", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the rebuild is building
  // When Marco opens "Assietta weekend" on Build the trip
  // Then "Plan the route" is disabled with the line "The road map is being rebuilt; planning is back at about 22:20."
  // And the trip and the exports of earlier routes stay readable
});

// @US-30 @ui
test.fixme("A successful rebuild shows the new regions and date everywhere", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the rebuild ended well
  // When Marco opens Build the trip
  // Then "Roads loaded for" names the new regions and "Map data" the new date
  // And the "Road map" screen says the rebuild is done
});

// @US-30 @ui @error
test.fixme("A failed rebuild brings the old map back and says why", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the Pi has 18 GB of free disk and the rebuild needs 25 GB
  // When Marco opens "Road map"
  // Then it says the rebuild failed, why, in plain words, and that the change is kept
  // And the earlier map, its regions and its date are served, and planning works
});

// @US-30 @ui @edge
test.fixme("A planned rebuild starts at its time and the result is there next morning", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given Marco planned a rebuild for 02:00 and closed the page
  // When he opens "Road map" on his phone at 08:00
  // Then it shows the result of the rebuild that began at 02:00 and not before
});

// @US-30 @ui @error @edge
test.fixme("A rebuild interrupted by a power cut ends with the old map served", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the rebuild was building when the Pi lost power and the Pi has restarted
  // When Marco opens "Road map"
  // Then the earlier map is served again and the result says the rebuild was interrupted, with the change kept
  // And if the switch to the new map had already happened, the result says the rebuild is done and the new regions are shown
});

// @US-31 @ui
test.fixme("Marco picks now or a start time", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given a pending change adds Portugal
  // When he chooses "Rebuild now"
  // Then the rebuild is waiting to start within a minute
});

// @US-31 @ui
test.fixme("Marco picks a start time", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given a pending change adds Portugal
  // When he chooses tonight 02:00
  // Then the screen says "Rebuild planned for tonight 02:00"
});

// @US-31 @ui @edge
test.fixme("A planned rebuild can be cancelled until it starts", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given a rebuild is planned for tonight 02:00
  // When Marco cancels it at 22:00
  // Then nothing is pending and the loaded regions and map date are unchanged
});

// @US-31 @ui @edge @error
test.fixme("A rebuild cannot be cancelled once it has started", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given a rebuild has just started at 02:00
  // When Marco presses "Cancel" at 02:01
  // Then the screen says it has already started and the rebuild goes on
});

// @US-31 @ui @edge @error
test.fixme("Refresh map data is the same workflow", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the road map has the eight regions and Marco is on the "Road map" screen
  // When he presses "Refresh map data" with the same regions
  // Then the screen shows its size and time and offers "Rebuild now" or a start time
});

// @US-31 @ui @edge @error
test.fixme("While a change is pending or running a second change is refused", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given a refresh of the map data is pending
  // When Marco tries to add another region
  // Then the second change is refused until the first is applied or cancelled
});

// @US-31 @ui @edge @error
test.fixme("One rebuild a day, counted by the kept map, with the next time shown", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given a rebuild ended well on 27 November 2026 UTC and Marco is in Milan
  // When he tries to start another the same UTC day
  // Then the screen refuses it and says the next rebuild can start from 01:00 on 28 November
  // And a rebuild that failed before the switch to the new map leaves no map that day, so it does not use the day up
  // And a rebuild that failed after the switch keeps its map and does use the day up
});

// @US-31 @ui @error
test.fixme("Without the helper the screen says rebuilds are not set up", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the helper is not installed on the Pi
  // When Marco opens "Road map" and tries to apply a change
  // Then the screen says rebuilds are not set up on the Pi and refuses the change
  // And the loaded regions and the page's other functions are unchanged
});

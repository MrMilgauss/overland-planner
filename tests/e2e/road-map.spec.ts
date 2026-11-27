// Slice 12c the planner knows its map (US-27 to US-31): the @ui scenarios of
// tests/acceptance/overland_route_planner_mvp/slice-12c-the-planner-knows-its-map.feature, one test per scenario, named
// after it (DISTILL D312). Every test runs in CI job 7 on chromium and webkit-iphone14 (step 13-30); the Gherkin
// lines are kept in each body as the plan.
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
import { rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
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
  // The page is ready when its map is drawn: it is the last thing to mount after the trip, the coverage and the runs are
  // read, and on webkit its start-up work can swallow a click made before.
  await expect(
    page.getByRole("button", { name: "Click on map to add" }),
  ).toBeVisible();
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

// The planner's GEOFABRIK_INDEX_URL points at a local stand-in (.github/scripts/fake-geofabrik.py): the real service is
// never asked. The planner keeps the list a week, so what the page sent is read from the browser's own requests.
const header = (page: Page): Locator =>
  page.getByRole("navigation", { name: "Main" });

async function openTheRoadMap(page: Page): Promise<void> {
  await page.goto("/");
  await header(page).getByRole("link", { name: "Road map" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Road map" }),
  ).toBeVisible();
}

const loaded = (page: Page): Locator =>
  page.getByRole("list", { name: "Loaded regions" });

// Marco is in Milan: the times of the screen are read in the browser's own zone.
test.use({ timezoneId: "Europe/Rome" });

// The helper's folder (ROAD_MAP_CHANGES_DIR of the planner): a fresh "helper-seen" is the helper being set up, and a real
// POST writes request.txt there. Both projects run at the same time against the one planner and the one folder, so only
// the tests that really write a change run on chromium (`needsTheFolder`), which leaves the folder as it found it;
// "helper-seen" is written before each test and never removed (the helper's absence is set with `answerWith`).
const CHANGES_DIR = join(process.env.ROAD_MAP_FIXTURE_DIR ?? "", "changes");
const WRITTEN = ["request.txt", "cancelled.txt", "running.txt"];
test.beforeEach(() => {
  writeFileSync(join(CHANGES_DIR, "helper-seen"), "");
});
test.afterEach(({}, testInfo) => {
  if (testInfo.project.name !== "chromium") return;
  for (const note of WRITTEN) rmSync(join(CHANGES_DIR, note), { force: true });
});
const needsTheFolder = (testInfo: TestInfo): void =>
  test.skip(
    testInfo.project.name !== "chromium",
    "writes a real change into the folder both projects share",
  );

// A start time for the real planner that never depends on today's date: five days ahead (the planner takes two minutes
// to fourteen days) at 02:00 in Milan, as the "datetime-local" field holds it, so never on the fixture map's day.
function fiveDaysAhead(): string {
  const day = new Date(Date.now() + 5 * 86_400_000).toLocaleDateString(
    "sv-SE",
    { timeZone: "Europe/Rome" },
  );
  return `${day}T02:00`;
}

const planned = (page: Page): Locator =>
  page.getByRole("region", { name: "Planned rebuild" });

// Marco picks a start time in the summary and presses "Rebuild road map".
async function rebuildAt(page: Page, typed: string): Promise<void> {
  const summary = page.getByRole("region", { name: "Size and time" });
  await summary.getByRole("radio", { name: "Start at a time" }).check();
  await summary.getByLabel("Start time").fill(typed);
  await summary.getByRole("button", { name: "Rebuild road map" }).click();
}

interface Real {
  served: { regions: { key: string }[] };
  change: Record<string, unknown>;
  limits: Record<string, unknown>;
}

// The real planner with a real change in the folder, except that the UTC day has no map yet whatever date the run
// happens on (the fixture map is dated 27 November 2026 and today's day would refuse the choice of a start). Unlike
// `answerWith`, the handler reads the planner's answer afresh for every GET, because the change it must show is the one
// this test's own real POST has just written; it still only fulfills with that answer, changed in one field.
async function dayHasNoMap(page: Page): Promise<void> {
  await page.route(/\/api\/road-map$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const real = (await (
      await page.request.get("/api/road-map")
    ).json()) as Real;
    return route.fulfill({
      json: { ...real, limits: { ...real.limits, next_rebuild_from: null } },
    });
  });
}

// For a plan that must not reach the folder (the fixture's map is dated 27 November 2026, and the planner refuses a
// same-day rebuild with "now" on that very day): the planner's real answers are read once (the road map, the cost of
// adding Portugal), the planner's POST is fulfilled with that cost and from then on the road map shows the plan.
// Returns what the browser sent.
async function planOnPaper(
  page: Page,
  piOffsetMinutes: number,
): Promise<{ start_at?: string | null; region_keys?: string[] }[]> {
  const real = (await (await page.request.get("/api/road-map")).json()) as Real;
  const found = (await (
    await page.request.get("/api/road-map/catalogue?q=Portugal")
  ).json()) as { results: { key: string; name: string }[] };
  const portugal = found.results.find((r) => r.name === "Portugal")!.key;
  const cost = await (
    await page.request.post("/api/road-map/change/preview", {
      data: {
        region_keys: [...real.served.regions.map((r) => r.key), portugal],
      },
    })
  ).json();
  let change = real.change;
  const sent: { start_at?: string | null; region_keys?: string[] }[] = [];
  await page.route(/\/api\/road-map$/, (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          json: {
            ...real,
            change,
            limits: { ...real.limits, next_rebuild_from: null },
            server_utc_offset_minutes: piOffsetMinutes,
          },
        })
      : route.continue(),
  );
  await page.route(/\/api\/road-map\/change$/, (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataJSON();
    sent.push(body);
    change = {
      state: "planned",
      start_at: body.start_at ?? null,
      added: cost.added,
      removed: [],
    };
    return route.fulfill({ status: 201, json: cost });
  });
  return sent;
}

interface RoadMapAnswer {
  limits: { next_rebuild_from: string | null };
  server_utc_offset_minutes: number;
}

// The planner's real answer, except that the day has no map yet (or has one, with the next time to start) and the Pi's
// clock is on the given offset: whether today's UTC day already holds a map depends on the date the run happens on.
async function answerRoadMapWith(
  page: Page,
  nextRebuildFrom: string | null,
  piOffsetMinutes: number,
): Promise<void> {
  await answerWith<RoadMapAnswer>(
    page,
    /\/api\/road-map$/,
    "/api/road-map",
    (real) => ({
      ...real,
      limits: { ...real.limits, next_rebuild_from: nextRebuildFrom },
      server_utc_offset_minutes: piOffsetMinutes,
    }),
  );
}

// Searches the free list of regions for the words and adds the named one as a pending change.
async function addRegion(
  page: Page,
  words: string,
  name: string,
): Promise<void> {
  const form = page.getByRole("form", { name: "Search for a region" });
  await form.getByLabel("Region name").fill(words);
  await form.getByRole("button", { name: "Search", exact: true }).click();
  await form.getByRole("button", { name: `Add ${name}` }).click();
}

const noSidewaysScrollAndBigTargets = async (page: Page): Promise<void> => {
  await page.setViewportSize(AT_PHONE);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  for (const button of await page.getByRole("button").all()) {
    if (!(await button.isVisible())) continue;
    expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  }
};

// @US-27 @ui
test("The Road map screen shows what is loaded", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the road map was rebuilt from the app and the served map has the eight regions, with map data of 27 November 2026
  const { served } = (await (
    await page.request.get("/api/road-map")
  ).json()) as Served;
  expect(served.regions).toHaveLength(8);
  // When Marco opens "Road map" from the header beside the projects
  await page.goto("/");
  const links = await header(page).getByRole("link").allTextContents();
  expect(links.slice(0, 2)).toEqual(["Projects", "Road map"]);
  await openTheRoadMap(page);
  // Then he sees the eight regions by name and "Map data: 27 November 2026"
  await expect(loaded(page).getByRole("listitem")).toHaveCount(8);
  for (const region of served.regions)
    await expect(loaded(page)).toContainText(region.name);
  await expect(page.getByText("Map data: 27 November 2026")).toBeVisible();
  // And no file, script or setting needs to be edited to change them
  await expect(
    loaded(page).getByRole("button", { name: "Remove Austria" }),
  ).toBeVisible();
});

// @US-27 @ui @edge
test("Before the first rebuild from the app the screen says the regions are unknown", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the served map was built on 26 November 2026, before the app kept the regions of a map
  await answerWith<
    Served & { served: { map_date: string | null; total_bytes: number } }
  >(page, /\/api\/road-map$/, "/api/road-map", (real) => ({
    ...real,
    served: {
      ...real.served,
      known: false,
      map_date: "2026-11-26T12:00:00Z",
      regions: [],
      total_bytes: 0,
    },
  }));
  // When Marco opens "Road map"
  await openTheRoadMap(page);
  // Then he sees "Map coverage unknown" with the map date and no list of regions
  await expect(page.getByText("Map coverage unknown")).toBeVisible();
  await expect(page.getByText("Map data: 26 November 2026")).toBeVisible();
  await expect(loaded(page)).toHaveCount(0);
  // And he is offered "Refresh map data" to build the same eight regions again
  await expect(
    page.getByRole("button", { name: "Refresh map data" }),
  ).toBeVisible();
});

// @US-27 @ui
test("A region is added by searching the free list of regions by name", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the road map has the eight regions and Marco is on the "Road map" screen
  await openTheRoadMap(page);
  await expect(loaded(page).getByRole("listitem")).toHaveCount(8);
  const form = page.getByRole("form", { name: "Search for a region" });
  await expect(form).toContainText("Geofabrik");
  const searches: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/road-map/catalogue"))
      searches.push(request.url());
  });
  await form.getByLabel("Region name").fill("Utah");
  // typing sends nothing: the list is asked only when Search is pressed
  expect(searches).toEqual([]);
  await form.getByRole("button", { name: "Search", exact: true }).click();
  // When he searches "Utah" and adds the result
  await expect(
    form.getByRole("list", { name: "Search results" }),
  ).toContainText("United States of America");
  expect(searches).toHaveLength(1);
  await form.getByRole("button", { name: "Add Utah" }).click();
  // Then "Utah" is listed as "to be added" and the loaded regions are still the eight
  const pending = page.getByRole("list", { name: "Pending changes" });
  await expect(pending).toContainText("Utah");
  await expect(pending).toContainText("to be added");
  await expect(loaded(page).getByRole("listitem")).toHaveCount(8);
  await expect(loaded(page)).not.toContainText("Utah");
  // And the screen says Utah is not linked by land to the other regions, as information only
  await expect(page.getByRole("status")).toContainText(
    "Utah is not linked by land to your other regions",
  );
  // At 390 px: no sideways scroll, targets of 44 px, the form in the page flow
  await page.setViewportSize(AT_PHONE);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  for (const button of await page.getByRole("button").all()) {
    if (!(await button.isVisible())) continue;
    expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  }
  expect(await form.evaluate((node) => getComputedStyle(node).position)).toBe(
    "static",
  );
});

// @US-27 @ui @edge
test("A region is removed as a pending change", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the loaded regions include Austria
  await openTheRoadMap(page);
  const austria = loaded(page)
    .getByRole("listitem")
    .filter({ hasText: "Austria" });
  await expect(austria).toHaveCount(1);
  // When Marco removes Austria
  await austria.getByRole("button", { name: "Remove Austria" }).click();
  // Then Austria is listed as "to be removed" and is still loaded until a rebuild ends well
  await expect(austria).toContainText("to be removed");
  await expect(loaded(page).getByRole("listitem")).toHaveCount(8);
  const { served } = (await (
    await page.request.get("/api/road-map")
  ).json()) as Served;
  expect(served.regions.map((region) => region.name)).toContain("Austria");
});

// @US-27 @ui
test("Size and time are shown before applying", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  await answerRoadMapWith(page, null, 60);
  // Given Marco has added Portugal
  await openTheRoadMap(page);
  await addRegion(page, "Portugal", "Portugal");
  // Then the screen shows "Total download 6.8 GB", about 58 minutes in all and about 41 without planning
  const summary = page.getByRole("region", { name: "Size and time" });
  await expect(summary).toContainText("Total download 6.8 GB");
  await expect(summary).toContainText("about 58 minutes in all");
  await expect(summary).toContainText("about 41 without planning");
  await expect(summary).toContainText("Estimate");
  await expect(summary).toContainText("Adds Portugal");
  // And "Rebuild road map" is offered, and the loaded regions are still the eight
  await expect(
    summary.getByRole("button", { name: "Rebuild road map" }),
  ).toBeVisible();
  await expect(loaded(page).getByRole("listitem")).toHaveCount(8);
  await noSidewaysScrollAndBigTargets(page);
});

// @US-27 @ui @error
test("Too big is refused with the size", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  await answerRoadMapWith(page, null, 60);
  // Given Marco has added Portugal
  await openTheRoadMap(page);
  await addRegion(page, "Portugal", "Portugal");
  await expect(
    page.getByRole("region", { name: "Size and time" }),
  ).toContainText("Total download 6.8 GB");
  // When he adds "North America" and the total goes above the limit of 8 GB
  await addRegion(page, "North America", "North America");
  // Then the screen refuses it, saying the size and the limit, and the pending change is unchanged
  await expect(page.getByRole("alert")).toContainText("20.8 GB");
  await expect(page.getByRole("alert")).toContainText("the limit is 8 GB");
  const pending = page.getByRole("list", { name: "Pending changes" });
  await expect(pending).toContainText("Portugal");
  await expect(pending).not.toContainText("North America");
  await expect(
    page.getByRole("region", { name: "Size and time" }),
  ).toContainText("Total download 6.8 GB");
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

// A rebuild adding Portugal is at `step` (the planner's own answer otherwise, W4: read once, only fulfilled). From the
// build until the switch ends the planner says planning is paused and when it is back; `backAt` is that instant.
type RebuildStep = "checking" | "downloading" | "building" | "switching";
const STEP_NUMBER: Record<RebuildStep, number> = {
  checking: 0,
  downloading: 1,
  building: 2,
  switching: 3,
};
async function rebuildIsAt(
  page: Page,
  step: RebuildStep,
  backAt: number | null,
): Promise<void> {
  await answerWith<Real>(page, /\/api\/road-map$/, "/api/road-map", (real) => ({
    ...real,
    change: {
      state: "running",
      step,
      steps_done: STEP_NUMBER[step],
      start_at: null,
      added: [{ key: "portugal", name: "Portugal" }],
      removed: [],
    },
    planning_paused: backAt !== null,
    planning_back_at: backAt === null ? null : new Date(backAt).toISOString(),
  }));
}

// The time as Marco's browser says it (Milan): "21:48".
const inMilan = (instant: number): string =>
  new Date(instant).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "Europe/Rome",
  });

// "Spagna test" holds Torino (Start and End) and Milano, planned on the offline road map as usual.
async function planATrip(page: Page, testInfo: TestInfo): Promise<void> {
  await serveTheBaseMap(page, testInfo);
  await newProject(page, testInfo);
  await expect(page.getByText("Roads loaded for:")).toBeVisible();
  await addPlaceOnTheForm(page, "Torino", "45.0703", "7.6869");
  await setFromTheRow(page, "Torino", "Set as start");
  await setFromTheRow(page, "Torino", "Set as end");
  await addPlaceOnTheForm(page, "Milano", "45.4642", "9.19");
}

// @US-30 @ui
test("Progress shows the step the rebuild is in", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given a rebuild adding Portugal has started and is building, 31 minutes from the end of the pause
  const now = Date.parse("2026-11-27T20:17:00Z");
  await page.clock.setFixedTime(now);
  await rebuildIsAt(page, "building", now + 31 * 60_000);
  // When Marco opens "Road map"
  await openTheRoadMap(page);
  // Then he sees which step it is in (the earlier steps ticked, the building one marked, the switch still to come)
  const steps = page.getByRole("region", { name: "Rebuild progress" });
  await expect(steps.getByRole("listitem")).toHaveText([
    "Waiting done",
    "Checking the Pi's disk and memory done",
    "Downloading done",
    "Building",
    "Switching to the new map",
  ]);
  await expect(steps.locator('[aria-current="step"]')).toHaveText("Building");
  // and the time left comes from the building step's own start
  await expect(steps).toContainText("about 31 minutes left");
  // And the loaded regions and map date are still those of the served map
  await expect(loaded(page).getByRole("listitem")).toHaveCount(8);
  await expect(page.getByText("Map data: 27 November 2026")).toBeVisible();
});

// @US-30 @ui @edge
test("During the download the old map keeps planning", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  // Given the rebuild is downloading
  await rebuildIsAt(page, "downloading", null);
  // When Marco plans his trip
  await planATrip(page, testInfo);
  const plan = page.getByRole("button", { name: "Plan the route" });
  await expect(plan).toBeEnabled();
  await expect(page.getByText("The road map is being rebuilt;")).toHaveCount(0);
  await plan.click();
  // Then the route is planned on the old map as usual
  await expect(
    page.getByRole("region", { name: "Your route", exact: true }),
  ).toBeVisible({ timeout: 90_000 });
});

// @US-30 @ui @edge
test("During the build planning is disabled and the page says until when", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize(AT_LAPTOP);
  // Given a route was planned before the rebuild reached its build
  await planATrip(page, testInfo);
  await page.getByRole("button", { name: "Plan the route" }).click();
  await expect(
    page.getByRole("region", { name: "Your route", exact: true }),
  ).toBeVisible({ timeout: 90_000 });
  // and the rebuild is building, planning back in 31 minutes
  const back = Date.now() + 31 * 60_000;
  await rebuildIsAt(page, "building", back);
  // When Marco opens the project again on Build the trip
  await page.reload();
  await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible();
  await page.getByRole("button", { name: "Edit trip" }).click();
  // Then "Plan the route" is disabled with the line
  await expect(
    page.getByRole("button", { name: "Plan the route" }),
  ).toBeDisabled();
  await expect(
    page.getByText(
      `The road map is being rebuilt; planning is back at about ${inMilan(back)}.`,
    ),
  ).toBeVisible();
  // And the trip and the exports of earlier routes stay readable
  await expect(tripList(page).getByRole("listitem")).toHaveCount(2);
  await expect(page.getByText("Torino")).toBeVisible();
});

// What the planner says of a rebuild that ended (the words are its own, as messages.py words them; the page shows them
// as they are), with the served map as it is after it: the real answer read once, changed, fulfilled (W4).
interface Rebuilt {
  served: {
    map_date: string | null;
    total_bytes: number;
    regions: Record<string, unknown>[];
  };
  change: Record<string, unknown>;
}
const PORTUGAL = { key: "portugal", name: "Portugal" };
const OLD_DAY = "27 November 2026";

// The planner's answer for the road map, which the test can change later (the page is opened again to read it): every GET
// is fulfilled with the current copy, none is fetched.
async function roadMapAnswers(
  page: Page,
  offsetMinutes = 60,
): Promise<{
  real: Rebuilt;
  set: (change: (real: Rebuilt) => Rebuilt) => void;
}> {
  const real = (await (
    await page.request.get("/api/road-map")
  ).json()) as Rebuilt;
  let current = real;
  await page.route(/\/api\/road-map$/, (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          json: {
            ...current,
            server_utc_offset_minutes: offsetMinutes,
            limits: {
              ...(current as unknown as { limits: object }).limits,
              next_rebuild_from: null,
            },
          },
        })
      : route.continue(),
  );
  return { real, set: (change) => (current = change(real)) };
}

// The served map after Portugal was added, on 28 November 2026.
const withPortugal = (real: Rebuilt): Rebuilt["served"] => ({
  ...real.served,
  map_date: "2026-11-28T01:00:00Z",
  regions: [
    ...real.served.regions,
    { ...real.served.regions[0], ...PORTUGAL, parent_name: "Europe" },
  ],
});
const namesOf = (served: Rebuilt["served"]): string[] =>
  served.regions.map((r) => r.name as string);
const joined = (names: string[]): string =>
  `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;

const DONE_WORDS =
  "Road map rebuilt on 28 November at 02:56. Portugal added; 9 regions, map data 28 November 2026.";
const DISK_WORDS =
  "The rebuild didn't finish: the Pi has 18 GB of free disk and needs 25 GB. The previous road map is back (map data 27 November 2026); nothing is lost. Your change is kept: free some space and press Rebuild road map again.";
const POWER_WORDS =
  "The rebuild didn't finish: the Pi lost power or restarted during the rebuild. The previous road map is back (map data 27 November 2026); nothing is lost. Your change is kept: press Rebuild road map again.";

const ended = (
  state: "done" | "failed",
  code: string | null,
  message: string,
  finishedAt: string,
): Rebuilt["change"] => ({
  state,
  start_at: null,
  added: state === "failed" ? [PORTUGAL] : [],
  removed: [],
  result: { code, message, finished_at: finishedAt },
});
const resultOfTheRebuild = (page: Page): Locator =>
  page.getByRole("region", { name: "Rebuild result" });

// @US-30 @ui
test("A successful rebuild shows the new regions and date everywhere", async ({
  page,
}, testInfo) => {
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given the rebuild ended well: the planner serves nine regions with map data of 28 November 2026
  const { real, set } = await roadMapAnswers(page);
  set((r) => ({
    ...r,
    served: withPortugal(r),
    change: ended("done", null, DONE_WORDS, "2026-11-28T01:56:00Z"),
  }));
  // When Marco opens Build the trip
  await newProject(page, testInfo);
  // Then "Roads loaded for" names the new regions and "Map data" the new date
  await expect(
    page.getByText(
      `Roads loaded for: ${joined([...namesOf(real.served), "Portugal"])}`,
    ),
  ).toBeVisible();
  await expect(page.getByText("Map data: 28 November 2026")).toBeVisible();
  // And the "Road map" screen says the rebuild is done
  await header(page).getByRole("link", { name: "Road map" }).click();
  await expect(resultOfTheRebuild(page)).toContainText(DONE_WORDS);
  await expect(loaded(page).getByRole("listitem")).toHaveCount(9);
  await expect(page.getByText("Map data: 28 November 2026")).toBeVisible();
});

// @US-30 @ui @error
test("A failed rebuild brings the old map back and says why", async ({
  page,
}, testInfo) => {
  await page.setViewportSize(AT_LAPTOP);
  await serveTheBaseMap(page, testInfo);
  // Given the Pi has 18 GB of free disk and the rebuild needs 25 GB
  const { set } = await roadMapAnswers(page);
  set((r) => ({
    ...r,
    change: ended("failed", "disk", DISK_WORDS, "2026-11-28T01:05:00Z"),
  }));
  // and the earlier map serves Marco's trip, planning works
  await planATrip(page, testInfo);
  await expect(
    page.getByRole("button", { name: "Plan the route" }),
  ).toBeEnabled();
  await expect(page.getByText("The road map is being rebuilt;")).toHaveCount(0);
  // When Marco opens "Road map"
  await header(page).getByRole("link", { name: "Road map" }).click();
  // Then it says the rebuild failed, why, in plain words, and that the change is kept (never a code)
  await expect(resultOfTheRebuild(page)).toContainText(DISK_WORDS);
  await expect(resultOfTheRebuild(page)).not.toContainText("disk_full");
  // And the earlier map, its regions and its date are served, and the change can be rebuilt again
  await expect(loaded(page).getByRole("listitem")).toHaveCount(8);
  await expect(page.getByText(`Map data: ${OLD_DAY}`)).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Pending changes" }),
  ).toContainText("Portugal");
  await expect(
    page.getByRole("button", { name: "Rebuild road map" }),
  ).toBeVisible();
});

// @US-30 @ui @edge
test("A planned rebuild starts at its time and the result is there next morning", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given Marco planned a rebuild for 02:00 (tonight, at 21:00 in Milan) and closed the page
  await page.clock.setFixedTime(Date.parse("2030-12-01T20:00:00Z"));
  const { set } = await roadMapAnswers(page, 60);
  set((r) => ({
    ...r,
    change: {
      state: "planned",
      start_at: "2030-12-02T01:00:00Z",
      added: [PORTUGAL],
      removed: [],
    },
  }));
  await openTheRoadMap(page);
  await expect(planned(page)).toContainText(
    "Rebuild planned for tonight 02:00",
  );
  await expect(resultOfTheRebuild(page)).toHaveCount(0);
  // When he opens "Road map" on his phone at 08:00, after the rebuild that began at 02:00
  const message =
    "Road map rebuilt on 2 December at 02:05. Portugal added; 9 regions, map data 2 December 2030.";
  set((r) => ({
    ...r,
    served: { ...withPortugal(r), map_date: "2030-12-02T01:00:00Z" },
    change: ended("done", null, message, "2030-12-02T01:05:00Z"),
  }));
  await page.clock.setFixedTime(Date.parse("2030-12-02T07:00:00Z"));
  await page.setViewportSize(AT_PHONE);
  await openTheRoadMap(page);
  // Then it shows the result of that rebuild, and the rebuild is no longer waiting
  await expect(resultOfTheRebuild(page)).toContainText(message);
  await expect(planned(page)).toHaveCount(0);
  await expect(loaded(page).getByRole("listitem")).toHaveCount(9);
});

// @US-30 @ui @error @edge
test("A rebuild interrupted by a power cut ends with the old map served", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the rebuild was building when the Pi lost power and the Pi has restarted
  const { set } = await roadMapAnswers(page);
  set((r) => ({
    ...r,
    change: ended("failed", "interrupted", POWER_WORDS, "2026-11-28T01:30:00Z"),
  }));
  // When Marco opens "Road map"
  await openTheRoadMap(page);
  // Then the earlier map is served again and the result says the rebuild was interrupted, with the change kept
  await expect(resultOfTheRebuild(page)).toContainText(POWER_WORDS);
  await expect(loaded(page).getByRole("listitem")).toHaveCount(8);
  await expect(page.getByText(`Map data: ${OLD_DAY}`)).toBeVisible();
  // And if the switch to the new map had already happened, the result says the rebuild is done and the new regions show
  set((r) => ({
    ...r,
    served: withPortugal(r),
    change: ended("done", null, DONE_WORDS, "2026-11-28T01:56:00Z"),
  }));
  await openTheRoadMap(page);
  await expect(resultOfTheRebuild(page)).toContainText(DONE_WORDS);
  await expect(loaded(page).getByRole("listitem")).toHaveCount(9);
});

// @US-31 @ui
test("Marco picks now or a start time", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  const sent = await planOnPaper(page, 60);
  // Given a pending change adds Portugal
  await openTheRoadMap(page);
  await addRegion(page, "Portugal", "Portugal");
  // When he chooses "Rebuild now"
  const summary = page.getByRole("region", { name: "Size and time" });
  const now = summary.getByRole("radio", { name: "Rebuild now" });
  await expect(now).toBeChecked();
  await expect(
    summary.getByRole("radio", { name: "Start at a time" }),
  ).not.toBeChecked();
  await expect(summary.getByLabel("Start time")).toBeHidden();
  await summary.getByRole("button", { name: "Rebuild road map" }).click();
  // Then the rebuild is waiting to start within a minute (the plan was sent without a start time)
  await expect(planned(page)).toContainText("Waiting to start within a minute");
  expect(sent).toHaveLength(1);
  expect(sent[0].start_at ?? null).toBeNull();
});

// @US-31 @ui
test("Marco picks a start time", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // The planner's clock is on UTC while Marco's browser is on Milan time
  const sent = await planOnPaper(page, 0);
  await page.clock.setFixedTime(Date.parse("2030-12-01T20:00:00Z"));
  // Given a pending change adds Portugal
  await openTheRoadMap(page);
  await addRegion(page, "Portugal", "Portugal");
  // When he chooses tonight 02:00 (here 2 December 2030, 02:00 in Milan; the browser's clock says it is 21:00 the evening before)
  const summary = page.getByRole("region", { name: "Size and time" });
  await summary.getByRole("radio", { name: "Start at a time" }).check();
  await summary.getByLabel("Start time").fill("2030-12-02T02:00");
  // Then the screen says when the rebuild would start, in his time, and "(Pi time)" because the Pi's zone differs
  await expect(summary).toContainText(
    "Rebuild at 02:00 on 2 December (Pi time)",
  );
  await summary.getByRole("button", { name: "Rebuild road map" }).click();
  // And, once planned, says "Rebuild planned for" that time; the planner got it as UTC
  await expect(planned(page)).toContainText(
    "Rebuild planned for tonight 02:00 (Pi time)",
  );
  expect(sent.map((p) => p.start_at)).toEqual(["2030-12-02T01:00:00.000Z"]);
});

// @US-31 @ui @edge
test("A planned rebuild can be cancelled until it starts", async ({
  page,
}, testInfo) => {
  needsTheFolder(testInfo);
  await page.setViewportSize(AT_LAPTOP);
  await dayHasNoMap(page);
  // Given a rebuild is planned for tonight 02:00 (here five days ahead for the real planner, so it takes it on any date;
  // the browser's clock says it is 21:00 the evening before)
  const start = fiveDaysAhead();
  await page.clock.setFixedTime(
    Date.parse(`${start}:00+01:00`) - 5 * 3_600_000,
  );
  await openTheRoadMap(page);
  await addRegion(page, "Portugal", "Portugal");
  await rebuildAt(page, start);
  await expect(planned(page)).toContainText(
    "Rebuild planned for tonight 02:00",
  );
  // When Marco cancels it at 22:00
  await planned(page).getByRole("button", { name: "Cancel" }).click();
  // Then nothing is pending and the loaded regions and map date are unchanged
  await expect(planned(page)).toHaveCount(0);
  await expect(loaded(page).getByRole("listitem")).toHaveCount(8);
  await expect(page.getByText("Map data: 27 November 2026")).toBeVisible();
});

// @US-31 @ui @edge @error
test("A rebuild cannot be cancelled once it has started", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given a rebuild has just started at 02:00 (the page still shows it as planned; the planner has no change waiting,
  // as after the helper took it, and refuses the cancel)
  await answerWith<Real>(page, /\/api\/road-map$/, "/api/road-map", (real) => ({
    ...real,
    change: {
      state: "planned",
      start_at: "2030-12-02T01:00:00Z",
      added: [],
      removed: [],
    },
  }));
  await openTheRoadMap(page);
  // When Marco presses "Cancel" at 02:01
  await planned(page).getByRole("button", { name: "Cancel" }).click();
  // Then the screen says it has already started and the rebuild goes on
  await expect(page.getByRole("alert")).toContainText("already started");
  await expect(planned(page)).toContainText("Rebuild planned for");
});

// @US-31 @ui @edge @error
test("Refresh map data is the same workflow", async ({ page }) => {
  await page.setViewportSize(AT_LAPTOP);
  await dayHasNoMap(page);
  // Given the road map has the eight regions and Marco is on the "Road map" screen
  await openTheRoadMap(page);
  const total = (await page.getByText(/^Total: /).innerText()).replace(
    "Total: ",
    "",
  );
  // When he presses "Refresh map data" with the same regions
  await page.getByRole("button", { name: "Refresh map data" }).click();
  // Then the screen shows its size and time and offers "Rebuild now" or a start time
  const summary = page.getByRole("region", { name: "Size and time" });
  await expect(summary).toContainText(`Total download ${total}`);
  await expect(summary).toContainText("Estimate");
  await expect(
    summary.getByRole("radio", { name: "Rebuild now" }),
  ).toBeVisible();
  await expect(
    summary.getByRole("radio", { name: "Start at a time" }),
  ).toBeVisible();
  await expect(loaded(page).getByRole("listitem")).toHaveCount(8);
});

// @US-31 @ui @edge @error
test("While a change is pending or running a second change is refused", async ({
  page,
}, testInfo) => {
  needsTheFolder(testInfo);
  await page.setViewportSize(AT_LAPTOP);
  await dayHasNoMap(page);
  // Given a refresh of the map data is pending
  await openTheRoadMap(page);
  await page.getByRole("button", { name: "Refresh map data" }).click();
  await rebuildAt(page, fiveDaysAhead());
  await expect(planned(page)).toContainText("Rebuild planned for 02:00");
  // When Marco tries to add another region
  await addRegion(page, "Portugal", "Portugal");
  await rebuildAt(page, fiveDaysAhead());
  // Then the second change is refused until the first is applied or cancelled
  await expect(page.getByRole("alert")).toContainText(
    "A change is already planned: apply or cancel it before planning another",
  );
  await expect(
    planned(page).getByRole("button", { name: "Cancel" }),
  ).toBeVisible();
});

// @US-31 @ui @edge @error
test("One rebuild a day, counted by the kept map, with the next time shown", async ({
  page,
}, testInfo) => {
  needsTheFolder(testInfo);
  await page.setViewportSize(AT_LAPTOP);
  // Given a rebuild ended well on 27 November 2026 UTC and Marco is in Milan (the Pi's clock is on Milan time too)
  await answerRoadMapWith(page, "2026-11-28T00:00:00Z", 60);
  // When he tries to start another the same UTC day
  await openTheRoadMap(page);
  await addRegion(page, "Portugal", "Portugal");
  // Then the screen refuses it and says the next rebuild can start from 01:00 on 28 November
  const summary = page.getByRole("region", { name: "Size and time" });
  await expect(summary.getByRole("alert")).toContainText(
    "The next rebuild can start from 01:00 on 28 November.",
  );
  await expect(summary).not.toContainText("Pi time");
  await expect(
    summary.getByRole("button", { name: "Rebuild road map" }),
  ).toHaveCount(0);
  // And a rebuild that failed before the switch to the new map leaves no map that day, so it does not use the day up
  // And a rebuild that failed after the switch keeps its map and does use the day up
  // (both are the planner's count of the kept maps, checked in the acceptance steps of US-31)
});

// @US-31 @ui @error
test("Without the helper the screen says rebuilds are not set up", async ({
  page,
}) => {
  await page.setViewportSize(AT_LAPTOP);
  // Given the helper is not installed on the Pi (the planner says it never looked at the changes folder)
  await answerWith<Real>(page, /\/api\/road-map$/, "/api/road-map", (real) => ({
    ...real,
    limits: { ...real.limits, rebuilds_set_up: false, helper_seen_at: null },
  }));
  // When Marco opens "Road map" and tries to apply a change
  await openTheRoadMap(page);
  // Then the screen says rebuilds are not set up on the Pi and refuses the change
  await expect(
    page.getByText("Rebuilds aren't set up on the Pi yet"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Refresh map data" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Region name")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Remove / })).toHaveCount(0);
  // And the loaded regions and the page's other functions are unchanged
  await expect(loaded(page).getByRole("listitem")).toHaveCount(8);
  await header(page).getByRole("link", { name: "Projects" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

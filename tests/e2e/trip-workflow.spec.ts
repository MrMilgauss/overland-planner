// Slice 12b trip workflow (US-23, US-24, US-25, US-26): the @ui scenarios of
// tests/acceptance/overland_route_planner_mvp/slice-12b-trip-workflow.feature, one test per scenario (one per row of
// each outline), named after it. Every test is `test.fixme` until DELIVER writes it in the step that builds its
// behaviour; the last step of the slice turns every `test.fixme` into `test` (DISTILL D292).
//
// Runs in CI job 7 on chromium (Desktop Chrome; 1440 x 900 set per test with `page.setViewportSize`) and
// webkit-iphone14 (390 px) against the packaged planner on PLANNER_URL, which plans on the offline road map. A test
// meant for one width skips itself on the other project (`test.skip(testInfo.project.name !== ...)`), as slice 12.
// Seeding follows ui-foundation.spec.ts with the 12b controls: the page itself (New project, "Add" -> "Upload GPX
// trails" / "Type coordinates" / "Click on the map", the row menu "Set as start" / "Set as end", "Plan the route") and
// `page.request` to the planner's own API. Each test creates its own project (both projects run at once).
//
// The base map never comes from the internet (CI has no network for it):
//  - the light base map: the address the planner names in `GET /api/config/map` (`base_style_url`, OpenFreeMap
//    Positron by default) is answered with CALM_STYLE below, a small style of the test's own (a background and one
//    empty label layer, so "the route above the base map's labels" can be read from the map's own layer order);
//  - the Terrain tiles and any other foreign request: a blank tile (serveBlankTiles, tests/e2e/blankTile.ts);
//  - "does not load" (US-26 S7): the Terrain tile host, or the style address, answered with `route.abort()`.
// Playwright runs the last-registered matching route first, so the style route is registered after the blank tiles.
//
// States the packaged planner cannot reach on its own (Loading, Planning, Couldn't plan, a Valhalla run, a retrace, a
// stopped plan, the large-project notice, an unanswering engine) are set by rewriting the planner's answer in this
// browser (policy waiver W4, as D275). Rule learned in slice 12 (D278, `434cf1c`): the real answer is read ONCE with
// `page.request` at setup and the route handler only fulfills the rewritten copy (`answerWith`); a handler never calls
// `route.fetch`, so a reload never races a pending fetch. A held answer (Loading) awaits a promise, then continues.
// The planner's lines (run time, reuse, failure, notices) are read from its answer and checked word for word (D211);
// run numbers and counts in the Gherkin are the owner's trip, not re-created by presses.
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  expect,
  test,
  type Locator,
  type Page,
  type TestInfo,
} from "@playwright/test";
import { contrastRatio, parseColour } from "./contrast";
import { CALM_STYLE, serveTheBaseMap } from "./blankTile";

// W4 without a race: the planner's real answer at `address` is read once now, changed, and every later request
// matching `pattern` is fulfilled with that copy. The handler never fetches.
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

// A ready run turned into a Valhalla run (W4): real roads, the provider line of the owner's map data.
const onRealRoads = (detail: Record<string, unknown>) => ({
  ...detail,
  estimate: false,
  provider_header: "Provider: Valhalla (map data 2026-11-18) / profile: 4x4",
});

const ASSIETTA_FILE =
  "../acceptance/overland_route_planner_mvp/fixtures/gpx/assietta.gpx";
const TORINO = "Casa Marco, Torino";

const tripList = (page: Page): Locator =>
  page.getByRole("list", { name: "Your trip" });
const addButton = (page: Page): Locator =>
  page.getByRole("button", { name: "Add", exact: true });

// Add -> "Upload GPX trails": the file chooser the menu item opens answers with the Assietta trail.
async function uploadTheTrail(page: Page, testInfo: TestInfo): Promise<void> {
  const before = await tripList(page).getByRole("listitem").count();
  const chooser = page.waitForEvent("filechooser");
  await addButton(page).click();
  await page.getByRole("menuitem", { name: "Upload GPX trails" }).click();
  await (
    await chooser
  ).setFiles(path.join(testInfo.project.testDir, ASSIETTA_FILE));
  await expect(tripList(page).getByRole("listitem")).toHaveCount(before + 1);
}

// Add -> "Type coordinates": a place of this name and these decimal degrees, listed.
async function addPlaceOnTheForm(
  page: Page,
  name: string,
  lat: string,
  lon: string,
): Promise<void> {
  const before = await tripList(page).getByRole("listitem").count();
  await addButton(page).click();
  await page.getByRole("menuitem", { name: "Type coordinates" }).click();
  const form = page.getByRole("form", { name: "Type coordinates" });
  await form.getByLabel("Name").fill(name);
  await form.getByLabel("Latitude").fill(lat);
  await form.getByLabel("Longitude").fill(lon);
  await form.getByRole("button", { name: "Add" }).click();
  await expect(tripList(page).getByRole("listitem")).toHaveCount(before + 1);
}

// The row menu of a place: "Set as start" or "Set as end".
async function setFromTheRow(
  page: Page,
  place: string,
  choice: "Set as start" | "Set as end",
): Promise<void> {
  const row = tripList(page).getByRole("listitem").filter({ hasText: place });
  await row.getByRole("button", { name: `Actions for ${place}` }).click();
  await page.getByRole("menuitem", { name: choice }).click();
}

async function newProject(
  page: Page,
  testInfo: TestInfo,
  label = "Assietta weekend",
): Promise<void> {
  const name = `${label} (${testInfo.project.name} ${Date.now()})`;
  await page.goto("/");
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "New project" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

// A new project of this test's own: the Assietta trail, Torino, and Torino as Start and End, each unless the options say
// no.
async function seedTrip(
  page: Page,
  testInfo: TestInfo,
  options: { trail?: boolean; place?: boolean; start?: boolean },
): Promise<void> {
  await newProject(page, testInfo);
  if (options.trail !== false) await uploadTheTrail(page, testInfo);
  if (options.place !== false) {
    await addPlaceOnTheForm(page, TORINO, "45.0703", "7.6869");
    if (options.start !== false) {
      await setFromTheRow(page, TORINO, "Set as start");
      await setFromTheRow(page, TORINO, "Set as end");
      await expect(tripList(page).getByText("not saved yet")).toHaveCount(0);
    }
  }
}

const projectIdOf = (url: string): string =>
  decodeURIComponent(/#\/projects\/([^/]+)$/.exec(url)![1]);

// The ids of the project's ready runs, oldest first, from the planner's own run list.
async function readyRunIds(page: Page, projectId: string): Promise<string[]> {
  const runs = (await (
    await page.request.get(`/api/projects/${projectId}/plan-runs`)
  ).json()) as { id: string; status: string }[];
  return runs.filter((run) => run.status === "ready").map((run) => run.id);
}

// ===================== US-23 Build the trip, plan it, see the route =====================

test("A project without a route opens on Build the trip", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await serveTheBaseMap(page, testInfo);
  await seedTrip(page, testInfo, { start: false });

  const panel = page.getByRole("region", { name: "Build the trip" });
  await expect(panel).toBeVisible();
  await expect(page.locator('[aria-current="step"]')).toHaveText(
    /Build the trip/,
  );
  const items = tripList(page);
  await expect(items.getByRole("listitem")).toHaveCount(2);
  await expect(items).toContainText("Assietta");
  await expect(items).toContainText(HOME);
  await expect(page.locator("[data-plan-state]")).toHaveText(/No plan yet/);
  await expect(page.locator("button.primary")).toHaveCount(1);
  await expect(
    panel.getByRole("button", { name: "Plan the route" }),
  ).toHaveClass(/primary/);
  await expect(page.getByRole("list", { name: "Itinerary" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Export GPX" })).toHaveCount(0);
  await expect(page.getByText("Route ready")).toHaveCount(0);
  await expect(page.getByText("Details", { exact: true })).toHaveCount(0);
});

test("Every way to add a stop is in one Add control and lands in the one list", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  test.setTimeout(120_000);
  await serveTheBaseMap(page, testInfo);
  await newProject(page, testInfo);
  await uploadTheTrail(page, testInfo);

  await addButton(page).click();
  await expect(page.getByRole("menu").getByRole("menuitem")).toHaveText([
    "Upload GPX trails",
    "Click on the map",
    "Type coordinates",
  ]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);

  await addPlaceOnTheForm(page, "Lago del Moncenisio", "45.2280", "6.9420");
  const items = tripList(page);
  await expect(items).toContainText("Lago del Moncenisio");
  await expect(items).toContainText("Strada dell'Assietta");

  // The map is drawn before any route (D288): the place as a dot, the trail's entry and exit.
  const map = page.getByRole("region", { name: "Map of the run" });
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible({
    timeout: 60_000,
  });
  await expect(map.locator(".run-marker.place")).toHaveCount(1);
  await expect(map.locator(".run-marker.entry")).toHaveCount(1);
  await expect(map.locator(".run-marker.exit")).toHaveCount(1);
});

test("Start and End are set on a place in the list", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  test.setTimeout(120_000);
  await serveTheBaseMap(page, testInfo);
  await seedTrip(page, testInfo, { start: false });
  const id = projectIdOf(page.url());
  const anchors = async (): Promise<(string | null)[]> =>
    (
      (await (await page.request.get(`/api/projects/${id}/items`)).json()) as {
        name: string;
        anchor: string | null;
      }[]
    ).map((item) => item.anchor);
  const row = (name: string): Locator =>
    tripList(page).getByRole("listitem").filter({ hasText: name });

  await setFromTheRow(page, TORINO, "Set as start");
  await expect(row(TORINO).getByText("Start", { exact: true })).toBeVisible();
  await expect(row(TORINO).getByText("not saved yet")).toBeVisible();
  expect(await anchors(), "nothing is sent until both are chosen").toEqual([
    null,
    null,
  ]);

  await setFromTheRow(page, TORINO, "Set as end");
  await expect(row(TORINO).getByText("Start", { exact: true })).toBeVisible();
  await expect(row(TORINO).getByText("End", { exact: true })).toBeVisible();
  await expect(row(TORINO).getByText("not saved yet")).toHaveCount(0);
  await expect.poll(anchors).toContain("start_end");

  await expect(row("Assietta").getByRole("button")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Set Start and End" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Start", { exact: true })).toHaveCount(0);
});

test("While planning, the trip is read-only and nothing is exported", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  test.setTimeout(240_000);
  await serveTheBaseMap(page, testInfo);
  const projectUrl = await planOnTheOfflineMap(page, testInfo);
  const id = projectIdOf(projectUrl);
  const runs = await readyRunIds(page, id);
  await answerWith<Record<string, unknown>>(
    page,
    new RegExp(`/api/plan-runs/${runs[0]}$`),
    `/api/plan-runs/${runs[0]}`,
    onRealRoads,
  );
  await page.reload();
  await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible();
  await page.getByRole("button", { name: "Edit trip" }).click();
  await addPlaceOnTheForm(page, "Lago del Moncenisio", "45.2280", "6.9420");
  await holdPlanning(page);

  await page.getByRole("button", { name: "Plan the route" }).click();

  const panel = page.getByRole("region", { name: "Planning" });
  await expect(panel).toBeVisible();
  await expect(page.locator("[data-plan-state]")).toHaveText(/Planning…/);
  await expect(page.getByRole("progressbar")).toBeVisible();
  const stop = panel.getByRole("button");
  await expect(stop).toHaveCount(1);
  await expect(stop).toHaveText("Stop and use best so far");
  await expect(tripList(page).getByRole("listitem")).toHaveCount(3);
  await expect(page.getByRole("button", { name: /^Add/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Import" })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Add", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Export GPX/ })).toHaveCount(0);
});

// The planner's own file name for a run's export, from its Content-Disposition header (D268).
async function exportName(page: Page, href: string): Promise<string> {
  const response = await page.request.get(href);
  const header = response.headers()["content-disposition"] ?? "";
  return /filename="?([^";]+)"?/.exec(header)![1];
}

// The panel's own Details (the map's attribution control is a <details> too).
const detailsOf = (page: Page): Locator =>
  page
    .getByRole("region", { name: "Your route", exact: true })
    .locator("details");
const openDetails = async (page: Page): Promise<void> => {
  await detailsOf(page).locator("summary").click();
};

// The page's own Details: one, closed, at the end of Your route.
async function expectOneClosedDetails(page: Page): Promise<void> {
  await expect(detailsOf(page)).toHaveCount(1);
  await expect(detailsOf(page).locator("summary")).toHaveText("Details");
  await expect(detailsOf(page)).not.toHaveAttribute("open", /.*/);
}

test("Stopping shows the best route found so far", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  test.setTimeout(240_000);
  await serveTheBaseMap(page, testInfo);
  const projectUrl = await planOnTheOfflineMap(page, testInfo);
  const [runId] = await readyRunIds(page, projectIdOf(projectUrl));
  const STOPPED = "not fully optimised (stopped)";
  // Held job (W4); after "Stop and use best so far" the job answers done with the real run's id, whose detail is
  // rewritten with not_fully_optimised "stopped" and its line (fulfill only).
  await answerWith<Record<string, unknown>>(
    page,
    new RegExp(`/api/plan-runs/${runId}$`),
    `/api/plan-runs/${runId}`,
    (detail) => ({
      ...onRealRoads(detail),
      not_fully_optimised: "stopped",
      messages: [...((detail.messages as string[] | undefined) ?? []), STOPPED],
    }),
  );
  let stopped = false;
  await page.route(/\/api\/projects\/[^/]+\/plan-runs$/, (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 202,
          json: { job_id: "held-job", notices: [] },
        })
      : route.continue(),
  );
  await page.route(/\/api\/plan-jobs\/held-job\/stop$/, (route) => {
    stopped = true;
    return route.fulfill({
      json: {
        state: "solving",
        reason: null,
        message: null,
        plan_run_id: null,
        elapsed_s: 2,
        stoppable: false,
      },
    });
  });
  await page.route(/\/api\/plan-jobs\/held-job$/, (route) =>
    route.fulfill({
      json: stopped
        ? {
            state: "done",
            reason: null,
            message: null,
            plan_run_id: runId,
            elapsed_s: 3,
            stoppable: false,
          }
        : {
            state: "solving",
            reason: null,
            message: null,
            plan_run_id: null,
            elapsed_s: 1.5,
            stoppable: true,
          },
    }),
  );
  await page.getByRole("button", { name: "Edit trip" }).click();
  await page.getByRole("button", { name: "Plan the route" }).click();
  await page.getByRole("button", { name: "Stop and use best so far" }).click();

  await expect(
    page.getByRole("region", { name: "Your route", exact: true }),
  ).toBeVisible();
  await expect(stateBadge(page)).toHaveText(/Route ready/);
  await expect(
    page.getByText("Not fully optimised", { exact: true }),
  ).toBeVisible();
  await expectOneClosedDetails(page);
  await expect(page.getByText(STOPPED, { exact: true })).toBeHidden();
  await openDetails(page);
  await expect(
    detailsOf(page).getByText(STOPPED, { exact: true }),
  ).toBeVisible();
});

test("Edit trip goes back to building and the shown route goes out of date", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  test.setTimeout(240_000);
  await serveTheBaseMap(page, testInfo);
  await planOnTheOfflineMap(page, testInfo);
  await page.getByRole("button", { name: "Edit trip" }).click();
  const map = page.getByRole("region", { name: "Map of the run" });
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible({
    timeout: 60_000,
  });
  await expect(map.locator(".run-marker.place")).toHaveCount(1); // the items, not the route

  await addButton(page).click();
  await page.getByRole("menuitem", { name: "Click on the map" }).click();
  const toggle = map.getByRole("button", { name: "Click on map to add" });
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  const frame = (await map.locator("canvas.maplibregl-canvas").boundingBox())!;
  await page.mouse.click(
    frame.x + frame.width * 0.8,
    frame.y + frame.height * 0.75,
  );
  const form = page.getByRole("form", { name: "Add a place here" });
  await form.getByLabel("Name").fill("Lago del Moncenisio");
  await form.getByRole("button", { name: "Add" }).click();

  const panel = page.getByRole("region", { name: "Build the trip" });
  await expect(panel).toBeVisible();
  await expect(tripList(page)).toContainText("Lago del Moncenisio");
  await expect(page.locator("[data-plan-state]")).toHaveText(
    /Out of date, plan again/,
  );
  await expect(
    panel.getByRole("button", { name: "Plan the route" }),
  ).toHaveClass(/primary/);
});

test("A refusal keeps Marco on Build the trip with the planner's own words", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await serveTheBaseMap(page, testInfo);
  await seedTrip(page, testInfo, { start: false });
  const refusal = (await (
    await page.request.post(
      `/api/projects/${projectIdOf(page.url())}/plan-runs`,
    )
  ).json()) as { message: string };
  expect(refusal.message).toContain("Set the Start before calculating");

  await page.getByRole("button", { name: "Plan the route" }).click();

  await expect(
    page.getByRole("alert").filter({ hasText: refusal.message }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Build the trip" }),
  ).toBeVisible();
  await expect(tripList(page).getByRole("listitem")).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "Plan the route" }),
  ).toBeEnabled();
});

// ===================== US-24 The route is the main result =====================

type RunDetail = {
  number: number;
  totals: Record<string, number> | null;
  stops: Record<string, unknown>[];
};

const RETRACE_REASON =
  "retraces the trail backwards; check it is drivable in reverse";
const SOMMEILLER = "Colle del Sommeiller";

// The packaged planner's one-trail run on real roads (W4: detail rewritten with onRealRoads, fulfill only), its page
// opened with the map's own hook (`?e2e=1`). `fillers` places before the trail make its step and its marker the
// (fillers + 2)th, as in the owner's longer trip; `retrace` adds the 12.4 km retrace of Colle del Sommeiller to the
// detail and the geometry, the trail itself being named after it.
async function openARealRoadRun(
  page: Page,
  testInfo: TestInfo,
  options: { fillers?: number; retrace?: boolean } = {},
): Promise<{ detail: RunDetail; geometry: Geometry }> {
  test.setTimeout(300_000);
  await serveTheBaseMap(page, testInfo);
  const projectUrl = await planOnTheOfflineMap(page, testInfo);
  const [id] = await readyRunIds(page, projectIdOf(projectUrl));
  const fillers = options.fillers ?? 0;
  const detailAddress = `/api/plan-runs/${id}`;
  const geometryAddress = `${detailAddress}/geometry`;
  const real = (await (
    await page.request.get(detailAddress)
  ).json()) as RunDetail;
  const stops = [...real.stops];
  const filler = (i: number) => ({
    ...stops[0],
    name: `Place ${i}`,
    leg_km: 10,
    leg_s: 600,
    leg_confidence: "confirmed",
  });
  stops.splice(
    1,
    0,
    ...Array.from({ length: fillers }, (_, i) => filler(i + 1)),
  );
  if (options.retrace) {
    const trail = stops.find((stop) => stop.type === "track")!;
    trail.name = SOMMEILLER;
    stops.push({
      name: SOMMEILLER,
      type: "retrace",
      leg_km: null,
      leg_s: null,
      cumulative_km: null,
      cumulative_s: null,
      track_km: RETRACE_KM,
      offroad_s: 2_700,
      entry: null,
      exit: null,
      confidence: "unconfirmed",
      reason: RETRACE_REASON,
    });
  }
  await answerWith<Record<string, unknown>>(
    page,
    new RegExp(`${detailAddress}$`),
    detailAddress,
    (answer) => ({ ...onRealRoads(answer), stops }),
  );
  const changeGeometry = (answer: Geometry): Geometry => {
    const shifted = {
      ...answer,
      features: answer.features.map((feature) => {
        const p = feature.properties as Record<string, number | null>;
        const move = (n: number | null) =>
          n !== null && n >= 2 ? n + fillers : n;
        return {
          ...feature,
          properties: {
            ...feature.properties,
            stop: move(p.stop) as number,
            ...("end_stop" in p ? { end_stop: move(p.end_stop) } : {}),
          },
        };
      }),
    } as Geometry;
    return options.retrace ? withSommeillerRetrace(shifted) : shifted;
  };
  // The rewritten answer, for the checks below (page.request is not routed: it still reads the planner's own).
  const geometry = changeGeometry(
    (await (await page.request.get(geometryAddress)).json()) as Geometry,
  );
  await answerWith<Geometry>(
    page,
    new RegExp(`${geometryAddress}$`),
    geometryAddress,
    changeGeometry,
  );
  await page.goto(projectUrl.replace("/#/", "/?e2e=1#/"));
  await expect(
    page
      .getByRole("region", { name: "Map of the run" })
      .locator("canvas.maplibregl-canvas"),
  ).toBeVisible({ timeout: 60_000 });
  const detail = { ...real, stops } as RunDetail;
  return { detail, geometry };
}

const steps = (page: Page): Locator =>
  page.getByRole("list", { name: "Itinerary" }).getByRole("button");
const mapFrame = (page: Page): Locator =>
  page.getByRole("region", { name: "Map of the run" }).locator(".map");
const numberMarker = (page: Page, stop: number): Locator =>
  mapFrame(page)
    .locator(".run-marker.numbered")
    .filter({
      hasText: new RegExp(`^(S |E )?${stop}$|^S/E \\d+ and ${stop}$`),
    });

// What the map publishes on its frame: its centre, zoom and the stop it is selected on.
async function mapView(
  page: Page,
): Promise<{ centre: [number, number]; zoom: number; selected: string }> {
  return mapFrame(page).evaluate((frame) => ({
    centre: (frame as HTMLElement).dataset.center!.split(",").map(Number) as [
      number,
      number,
    ],
    zoom: Number((frame as HTMLElement).dataset.zoom),
    selected: (frame as HTMLElement).dataset.selectedStop ?? "",
  }));
}

// The middle of the box that holds every line and marker of `stop` in the planner's own geometry answer.
function middleOf(geometry: Geometry, stop: number): [number, number] {
  const points = geometry.features
    .filter((f) => {
      const p = f.properties as { stop: number; end_stop?: number | null };
      return p.stop === stop || p.end_stop === stop;
    })
    .flatMap((f) =>
      f.geometry.type === "LineString"
        ? (f.geometry.coordinates as [number, number][])
        : [f.geometry.coordinates as [number, number]],
    );
  const lons = points.map((point) => point[0]);
  const lats = points.map((point) => point[1]);
  return [
    (Math.min(...lons) + Math.max(...lons)) / 2,
    (Math.min(...lats) + Math.max(...lats)) / 2,
  ];
}

const km = (value: number): string => `${value.toFixed(1)} km`;
const hoursMinutes = (seconds: number): string => {
  const minutes = Math.round(seconds / 60);
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}`;
};

const dimmed = (page: Page, layer: string): Promise<string> =>
  page.evaluate(
    (id) =>
      JSON.stringify(
        (
          window as unknown as {
            __overlandRunMap: {
              getPaintProperty(layer: string, name: string): unknown;
            };
          }
        ).__overlandRunMap.getPaintProperty(id, "line-opacity"),
      ),
    layer,
  );

test("On a laptop the summary card and the first steps are in view", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  await page.setViewportSize({ width: 1440, height: 900 });
  const { detail } = await openARealRoadRun(page, testInfo);

  const region = page.getByRole("region", { name: "Your route", exact: true });
  await expect(region).toBeVisible();
  const totals = region.getByLabel("Totals");
  for (const text of [
    km(detail.totals!.total_km),
    hoursMinutes(detail.totals!.total_s),
    km(detail.totals!.road_km),
    hoursMinutes(detail.totals!.road_s),
    km(detail.totals!.offroad_km),
    hoursMinutes(detail.totals!.offroad_s),
  ])
    await expect(totals).toContainText(text);
  await expect(region.getByText("Real roads")).toBeVisible();

  const viewport = page.viewportSize()!;
  const map = (await page
    .getByRole("region", { name: "Map of the run" })
    .boundingBox())!;
  const card = (await totals.boundingBox())!;
  const first = steps(page);
  await expect(first).toHaveCount(detail.stops.length);
  for (const [index, step] of (await first.all()).slice(0, 3).entries()) {
    const box = (await step.boundingBox())!;
    expect(
      box.y + box.height,
      `step ${index + 1} is in the window without scrolling`,
    ).toBeLessThanOrEqual(viewport.height);
    expect(box.y, `step ${index + 1} is below the card`).toBeGreaterThan(
      card.y + card.height - 1,
    );
    expect(box.x, "right of the map").toBeGreaterThanOrEqual(
      map.x + map.width - 1,
    );
  }
  const main = region.getByRole("link", { name: "Export GPX" });
  await expect(main).toBeVisible();
  await expect(main).toHaveClass(/primary/);
  await expect(region.getByRole("button", { name: "Edit trip" })).toBeVisible();
});

test("An estimate route says Estimate in the card and on the map", async ({
  page,
}, testInfo) => {
  test.setTimeout(240_000);
  await serveTheBaseMap(page, testInfo);
  const projectUrl = await planOnTheOfflineMap(page, testInfo);
  const [id] = await readyRunIds(page, projectIdOf(projectUrl));
  const exported = await page.request.get(`/api/plan-runs/${id}/export.gpx`);
  const planners = /filename="?([^";]+)"?/.exec(
    exported.headers()["content-disposition"] ?? "",
  )![1];
  expect(planners).toMatch(/-run1-estimate\.gpx$/);

  const link = page.getByRole("link", { name: "Export GPX" });
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    link.click(),
  ]);

  expect(download.suggestedFilename()).toBe(planners);
  const card = page.getByRole("region", { name: "Your route" });
  await expect(card.getByRole("note", { name: ESTIMATE_NOTE })).toHaveText(
    /Estimate/,
  );
  await expect(
    page
      .getByRole("region", { name: "Map of the run" })
      .getByRole("note", { name: ESTIMATE_NOTE }),
  ).toHaveText(/Estimate/);
  await expect(page.getByText("Real roads")).toHaveCount(0);
});

test("Selecting a step moves the map to it", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  await page.setViewportSize({ width: 1440, height: 900 });
  const { detail, geometry } = await openARealRoadRun(page, testInfo);
  const stop = detail.stops.findIndex((s) => s.type === "track") + 1;

  await steps(page)
    .nth(stop - 1)
    .click();

  await expect
    .poll(async () => (await mapView(page)).selected)
    .toBe(String(stop));
  const after = await mapView(page);
  const [lon, lat] = middleOf(geometry, stop);
  expect(after.centre[0]).toBeCloseTo(lon, 2);
  expect(after.centre[1]).toBeCloseTo(lat, 2);
  expect(after.zoom).toBeLessThanOrEqual(13);
  await expect(numberMarker(page, stop)).toHaveClass(/selected/);
  expect(
    await numberMarker(page, stop).evaluate(
      (el) => getComputedStyle(el).boxShadow,
    ),
    "the marker is ringed in the accent colour",
  ).toContain("rgb(29, 78, 216)");
  await expect(steps(page).nth(stop - 1)).toHaveAttribute(
    "aria-current",
    "step",
  );
  expect(await dimmed(page, "road-confirmed")).toContain("0.35");

  await page.getByRole("button", { name: "Show whole route" }).click();
  await expect.poll(async () => (await mapView(page)).selected).toBe("");
  await expect(steps(page).nth(stop - 1)).not.toHaveAttribute(
    "aria-current",
    "step",
  );
  expect(await dimmed(page, "road-confirmed")).not.toContain("0.35");
  await expect(
    page.getByRole("button", { name: "Show whole route" }),
  ).toBeHidden();
});

test("Selecting a stop on the map highlights its step", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  await page.setViewportSize({ width: 1440, height: 900 });
  // The trail is the (fillers + 2)th stop, as the owner's stop 7 is a long way down the list.
  const { detail } = await openARealRoadRun(page, testInfo, { fillers: 5 });
  const stop = detail.stops.findIndex((s) => s.type === "track") + 1;
  expect(stop).toBe(7);
  const step = steps(page).nth(stop - 1);
  await expect(step).not.toHaveAttribute("aria-current", "step");

  await numberMarker(page, stop).click();

  await expect(step).toHaveAttribute("aria-current", "step");
  await expect(step).toBeInViewport();
  expect((await mapView(page)).selected).toBe(String(stop));
});

test("A retrace is its own step, linked to its own line", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  await page.setViewportSize({ width: 1440, height: 900 });
  const { detail, geometry } = await openARealRoadRun(page, testInfo, {
    retrace: true,
  });
  const stop = detail.stops.findIndex((s) => s.type === "retrace") + 1;
  const step = steps(page).nth(stop - 1);

  await step.click();

  await expect
    .poll(async () => (await mapView(page)).selected)
    .toBe(String(stop));
  const [lon, lat] = middleOf(geometry, stop);
  const view = await mapView(page);
  expect(view.centre[0]).toBeCloseTo(lon, 2);
  expect(view.centre[1]).toBeCloseTo(lat, 2);
  await expect(step).toContainText(RETRACE_REASON);
  await expect(step).toContainText(`${RETRACE_KM} km`);
  await expect(step).toContainText("off-road");
  await expect(step).toContainText("Back the same way");
  const named = steps(page).filter({ hasText: SOMMEILLER });
  await expect(named).toHaveCount(2);
  await expect(named.filter({ hasText: /Sommeiller\s*Trail/ })).toHaveCount(1);
  await expect(
    named.filter({ hasText: /Sommeiller\s*Back the same way/ }),
  ).toHaveCount(1);
});

test("On a phone the map follows the selected step", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "webkit-iphone14", "the phone profile");
  const { detail } = await openARealRoadRun(page, testInfo);
  const stop = detail.stops.findIndex((s) => s.type === "track") + 1;
  const step = steps(page).nth(stop - 1);
  await step.scrollIntoViewIfNeeded();
  const frame = page.getByRole("region", { name: "Map of the run" });
  await expect(frame).not.toBeInViewport({ ratio: 0.5 });

  await step.tap();

  await expect(frame).toBeInViewport({ ratio: 0.5 });
  expect((await mapView(page)).selected).toBe(String(stop));
  await expect(numberMarker(page, stop)).toHaveClass(/selected/);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    ),
    "no sideways scroll",
  ).toBe(false);
  for (const each of await steps(page).all())
    expect((await each.boundingBox())!.height).toBeGreaterThanOrEqual(43.5);
});

// ===================== US-25 The status in user words, engine details behind Details =====================

type StateLook = { glyph: string; border: string; fill: string };

// The D266 table with the D284 words: what each status shows besides its colour. Two statuses never share glyph,
// border style and fill.
const STATE_LOOKS: Record<string, StateLook> = {
  "No plan yet": { glyph: "", border: "dashed", fill: "outline" },
  Loading: { glyph: "", border: "solid", fill: "outline" },
  "Planning…": { glyph: "", border: "solid", fill: "filled" },
  "Route ready": { glyph: "\u2713", border: "solid", fill: "filled" },
  "Couldn't plan": { glyph: "\u2715", border: "solid", fill: "filled" },
  "Out of date, plan again": { glyph: "!", border: "solid", fill: "filled" },
};

const stateBadge = (page: Page): Locator => page.locator("[data-plan-state]");

// The badge as the page draws it: its words without the glyph, the glyph, the border style and whether it is filled.
async function badgeLook(
  badge: Locator,
): Promise<StateLook & { label: string }> {
  return badge.evaluate((el) => {
    const style = getComputedStyle(el);
    const glyph = el.querySelector('[aria-hidden="true"]');
    const words = el.cloneNode(true) as HTMLElement;
    words.querySelectorAll('[aria-hidden="true"]').forEach((g) => g.remove());
    const fill = /^rgba?\(.*,\s*0\)$|^transparent$/.test(style.backgroundColor)
      ? "outline"
      : "filled";
    return {
      label: (words.textContent ?? "").trim(),
      glyph: (glyph?.textContent ?? "").trim(),
      border: style.borderTopStyle,
      fill,
    };
  });
}

async function expectStatus(page: Page, label: string): Promise<void> {
  const looks = Object.values(STATE_LOOKS).map((l) => JSON.stringify(l));
  expect(new Set(looks).size, "no two statuses share glyph, border, fill").toBe(
    looks.length,
  );
  await expect(stateBadge(page)).toHaveCount(1);
  await expect(stateBadge(page)).toBeVisible();
  await expect
    .poll(() => badgeLook(stateBadge(page)))
    .toEqual({ label, ...STATE_LOOKS[label] });
}

// Planning without a real solve (W4, fulfill only): the answer to "Plan the route" and to the job, held at "solving".
async function holdPlanning(page: Page): Promise<void> {
  await page.route(/\/api\/projects\/[^/]+\/plan-runs$/, (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 202,
          json: { job_id: "held-job", notices: [] },
        })
      : route.continue(),
  );
  await page.route(/\/api\/plan-jobs\/held-job$/, (route) =>
    route.fulfill({
      json: {
        state: "solving",
        reason: null,
        message: null,
        plan_run_id: null,
        elapsed_s: 1.5,
        stoppable: true,
      },
    }),
  );
}

const FAILED_WORDS =
  "No valid route found within the time limit - plan run #2 failed";

for (const status of Object.keys(STATE_LOOKS)) {
  test(`Every status has its own words and look: ${status}`, async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "the desktop browser");
    test.setTimeout(300_000);
    await serveTheBaseMap(page, testInfo);

    if (status === "No plan yet") {
      await seedTrip(page, testInfo, { trail: false, place: false });
    } else if (status === "Loading") {
      await seedTrip(page, testInfo, { trail: false, place: false });
      const projectUrl = page.url();
      let release: () => void = () => {};
      const held = new Promise<void>((done) => (release = done));
      await page.goto("/");
      await page.route(/\/api\/projects\/[^/]+\/plan-runs$/, async (route) => {
        await held;
        await route.continue();
      });
      await page.goto(projectUrl);
      await expectStatus(page, status);
      await expect(stateBadge(page)).toHaveAttribute("aria-busy", "true");
      release();
      await expect(stateBadge(page)).toContainText("No plan yet");
      return;
    } else if (status === "Planning…") {
      await seedTrip(page, testInfo, {});
      await holdPlanning(page);
      await page.getByRole("button", { name: "Plan the route" }).click();
    } else if (status === "Route ready") {
      await planOnTheOfflineMap(page, testInfo);
    } else if (status === "Couldn't plan") {
      const projectUrl = await planOnTheOfflineMap(page, testInfo);
      const id = projectIdOf(projectUrl);
      await answerWith<object[]>(
        page,
        /\/api\/projects\/[^/]+\/plan-runs$/,
        `/api/projects/${id}/plan-runs`,
        (runs) => [
          ...runs,
          { id: "failed-run-2", number: 2, status: "failed", stale: false },
        ],
      );
      await page.route(/\/api\/plan-runs\/failed-run-2$/, (route) =>
        route.fulfill({
          json: {
            id: "failed-run-2",
            project_id: id,
            number: 2,
            status: "failed",
            failure_reason: "timeout",
            stops: [],
            totals: null,
            report: null,
            estimate: false,
            messages: [FAILED_WORDS],
          },
        }),
      );
      await page.reload();
      await expect(
        page.getByRole("alert").filter({ hasText: FAILED_WORDS }),
      ).toBeVisible();
    } else {
      await planOnTheOfflineMap(page, testInfo);
      await page.getByRole("button", { name: "Edit trip" }).click();
      await addPlaceOnTheForm(page, "Rifugio Selleries", "45.0123", "7.0456");
      await page.reload();
      await expect(
        page.getByRole("link", { name: "Export GPX" }),
      ).toBeVisible();
    }
    await expectStatus(page, status);
  });
}

test("Engine details wait behind one closed Details", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  test.setTimeout(300_000);
  await serveTheBaseMap(page, testInfo);
  // Real memo reuse: the same trip planned twice; the run's own lines are read with page.request.
  const projectUrl = await planOnTheOfflineMap(page, testInfo);
  const id = projectIdOf(projectUrl);
  await page.request.post(`/api/projects/${id}/plan-runs`);
  await expect
    .poll(async () => (await readyRunIds(page, id)).length, {
      timeout: 120_000,
    })
    .toBe(2);
  const runId = (await readyRunIds(page, id))[1];
  const real = (await (
    await page.request.get(`/api/plan-runs/${runId}`)
  ).json()) as { number: number; messages: string[]; provider_header: string };
  const rewritten = onRealRoads(real as unknown as Record<string, unknown>);
  await answerWith<Record<string, unknown>>(
    page,
    new RegExp(`/api/plan-runs/${runId}$`),
    `/api/plan-runs/${runId}`,
    onRealRoads,
  );
  expect(
    real.messages.some((line) => line.startsWith("Reused the identical plan")),
  ).toBe(true);

  await page.reload();

  const heading = `Plan run #${real.number}`;
  const REOPTIMISE = "Re-optimise (ignore previous result)";
  const lines = [
    heading,
    rewritten.provider_header as string,
    ...real.messages,
  ];
  await expect(stateBadge(page)).toHaveText(/Route ready/);
  for (const line of lines)
    await expect(page.getByText(line, { exact: true }).first()).toBeHidden();
  await expect(page.getByRole("button", { name: REOPTIMISE })).toBeHidden();
  await expectOneClosedDetails(page);

  await openDetails(page);
  const inside = detailsOf(page);
  const tops: number[] = [];
  for (const line of lines) {
    const found = inside.getByText(line, { exact: true });
    await expect(found).toBeVisible();
    tops.push((await found.boundingBox())!.y);
  }
  const button = inside.getByRole("button", { name: REOPTIMISE });
  await expect(button).toBeVisible();
  tops.push((await button.boundingBox())!.y);
  expect(tops, "the planner's order").toEqual([...tops].sort((a, b) => a - b));
});

test("Couldn't plan keeps the previous route and its export", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  test.setTimeout(300_000);
  await serveTheBaseMap(page, testInfo);
  const projectUrl = await planOnTheOfflineMap(page, testInfo);
  const id = projectIdOf(projectUrl);
  const [runId] = await readyRunIds(page, id);
  const real = (await (
    await page.request.get(`/api/plan-runs/${runId}`)
  ).json()) as { number: number };
  const failedNumber = real.number + 1;
  const words = `No valid route found within the time limit - plan run #${failedNumber} failed`;
  await answerWith<Record<string, unknown>>(
    page,
    new RegExp(`/api/plan-runs/${runId}$`),
    `/api/plan-runs/${runId}`,
    onRealRoads,
  );
  await answerWith<object[]>(
    page,
    /\/api\/projects\/[^/]+\/plan-runs$/,
    `/api/projects/${id}/plan-runs`,
    (runs) => [
      ...runs,
      {
        id: "failed-run",
        number: failedNumber,
        status: "failed",
        stale: false,
      },
    ],
  );
  await page.route(/\/api\/plan-runs\/failed-run$/, (route) =>
    route.fulfill({
      json: {
        id: "failed-run",
        project_id: id,
        number: failedNumber,
        status: "failed",
        failure_reason: "timeout",
        stops: [],
        totals: null,
        report: null,
        estimate: false,
        messages: [words],
      },
    }),
  );

  await page.reload();

  await expect(stateBadge(page)).toHaveText(/Couldn't plan/);
  const failure = page.getByRole("alert").filter({ hasText: words });
  await expect(failure).toBeVisible();
  await expect(failure.getByTitle(/^estimate:/)).toHaveCount(0);
  await expect(page.getByText("Previous route")).toBeVisible();
  await expect(page.getByRole("list", { name: "Itinerary" })).toBeVisible();
  await expectOneClosedDetails(page);
  await openDetails(page);
  await expect(
    detailsOf(page).getByText(`Plan run #${real.number}`, { exact: true }),
  ).toBeVisible();
  const link = page.getByRole("link", { name: "Export GPX" });
  await expect(link).toHaveCount(1);
  const own = await exportName(page, (await link.getAttribute("href"))!);
  const download = page.waitForEvent("download");
  await link.click();
  expect((await download).suggestedFilename()).toBe(own);
  expect(own).toMatch(new RegExp(`run${real.number}`));
});

test("Couldn't plan without an earlier route keeps Marco on Build the trip", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await serveTheBaseMap(page, testInfo);
  await seedTrip(page, testInfo, { trail: false, place: false });
  const words =
    "Routing engine unreachable - nothing was changed. Try again later.";
  await page.route(/\/api\/projects\/[^/]+\/plan-runs$/, (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 202,
          json: { job_id: "down-job", notices: [] },
        })
      : route.continue(),
  );
  await page.route(/\/api\/plan-jobs\/down-job$/, (route) =>
    route.fulfill({
      json: {
        state: "failed",
        reason: "routing_unavailable",
        message: words,
        plan_run_id: null,
        elapsed_s: 0.2,
        stoppable: false,
      },
    }),
  );

  await page.getByRole("button", { name: "Plan the route" }).click();

  await expect(stateBadge(page)).toHaveText(/Couldn't plan/);
  await expect(
    page.getByRole("alert").filter({ hasText: words }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Build the trip" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Plan the route" }),
  ).toBeEnabled();
  await expect(page.getByRole("link", { name: /Export GPX/ })).toHaveCount(0);
});

test("An out-of-date route asks to be planned again and can still be exported", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  test.setTimeout(300_000);
  await serveTheBaseMap(page, testInfo);
  await planOnTheOfflineMap(page, testInfo);
  await page.getByRole("button", { name: "Edit trip" }).click();
  await addPlaceOnTheForm(page, "Lago del Moncenisio", "45.2280", "6.9420");

  await page.reload();

  await expect(stateBadge(page)).toHaveText(/Out of date, plan again/);
  const route = page.getByRole("region", { name: "Your route", exact: true });
  await expect(route.getByRole("note", { name: /^estimate:/ })).toHaveCount(1);
  await expect(route.getByRole("list", { name: "Itinerary" })).toBeVisible();
  await expect(
    route.getByRole("button", { name: "Plan the route" }),
  ).toHaveClass(/primary/);
  const link = route.getByRole("link", { name: "Export GPX" });
  await expect(link).toBeVisible();
  await expect(link).not.toHaveClass(/primary/);
  const own = await exportName(page, (await link.getAttribute("href"))!);
  expect(own).toMatch(/-estimate\.gpx$/);
  const download = page.waitForEvent("download");
  await link.click();
  expect((await download).suggestedFilename()).toBe(own);
});

test("Planning an unchanged trip with a retrace reuses the route and keeps each stop once", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  test.setTimeout(300_000);
  await serveTheBaseMap(page, testInfo);
  const projectUrl = await planOnTheOfflineMap(page, testInfo);
  const id = projectIdOf(projectUrl);
  const [first] = await readyRunIds(page, id);
  const COLLE = "Colle del Sommeiller";
  // The planner's run with its trail named for the owner's trip and a retrace of it added (W4).
  const withRetrace = (detail: Record<string, unknown>) => {
    const stops = detail.stops as { name: string; type: string }[];
    const at = stops.findIndex((stop) => stop.type === "track");
    const trail = { ...stops[at], name: COLLE };
    return {
      ...detail,
      stops: [
        ...stops.slice(0, at),
        trail,
        {
          ...trail,
          type: "retrace",
          reason: "the trail is a dead end",
          confidence: "unconfirmed",
          leg_km: null,
          leg_s: null,
        },
        ...stops.slice(at + 1),
      ],
    };
  };
  await answerWith<Record<string, unknown>>(
    page,
    new RegExp(`/api/plan-runs/${first}$`),
    `/api/plan-runs/${first}`,
    (detail) => withRetrace(onRealRoads(detail)),
  );
  await page.reload();
  await expect(page.getByText(COLLE).first()).toBeVisible();

  await page.getByRole("button", { name: "Edit trip" }).click();
  await page.getByRole("button", { name: "Plan the route" }).click();
  await expect
    .poll(async () => (await readyRunIds(page, id)).length, {
      timeout: 120_000,
    })
    .toBe(2);
  const second = (await readyRunIds(page, id))[1];
  const real = (await (
    await page.request.get(`/api/plan-runs/${second}`)
  ).json()) as { messages: string[] };
  const reuse = real.messages.find((line) =>
    line.startsWith("Reused the identical plan of run #"),
  )!;
  expect(reuse).toBeTruthy();
  await answerWith<Record<string, unknown>>(
    page,
    new RegExp(`/api/plan-runs/${second}$`),
    `/api/plan-runs/${second}`,
    (detail) => withRetrace(onRealRoads(detail)),
  );
  await page.reload();

  await expect(stateBadge(page)).toHaveText(/Route ready/);
  const itinerary = page.getByRole("list", { name: "Itinerary" });
  await expect(
    itinerary.getByRole("listitem").filter({ hasText: COLLE }),
  ).toHaveCount(2);
  await expect(
    itinerary.getByText("Back the same way", { exact: true }),
  ).toHaveCount(1);
  await expect(
    itinerary
      .getByRole("listitem")
      .filter({ hasText: COLLE })
      .getByText("Trail", { exact: true }),
  ).toHaveCount(1);
  await expectOneClosedDetails(page);
  await openDetails(page);
  await expect(detailsOf(page).getByText(reuse, { exact: true })).toBeVisible();
  await expect(
    detailsOf(page).getByRole("button", {
      name: "Re-optimise (ignore previous result)",
    }),
  ).toBeVisible();
});

test("The planner's notices stay in view", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  test.setTimeout(120_000);
  await serveTheBaseMap(page, testInfo);
  await seedTrip(page, testInfo, {});
  const NOTICE = "Large project - calculation may take longer than 3 minutes";
  await page.route(/\/api\/projects\/[^/]+\/plan-runs$/, (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 202,
          json: { job_id: "held-job", notices: [NOTICE] },
        })
      : route.continue(),
  );
  await page.route(/\/api\/plan-jobs\/held-job$/, (route) =>
    route.fulfill({
      json: {
        state: "solving",
        reason: null,
        message: null,
        plan_run_id: null,
        elapsed_s: 1.5,
        stoppable: true,
      },
    }),
  );

  await page.getByRole("button", { name: "Plan the route" }).click();

  await expect(page.getByText(NOTICE, { exact: true })).toBeVisible();
  await expect(detailsOf(page).getByText(NOTICE)).toHaveCount(0);
});

// ===================== US-26 A calm map on which the route stands out =====================

const HOME = "Casa Marco, Torino";
const ESTIMATE_NOTE =
  "estimate: road legs are straight-line guesses, not real roads";
const ROUTE_LAYERS = [
  "unavailable",
  "road-confirmed",
  "road-unconfirmed",
  "retrace",
  "track",
];
const RETRACE_KM = 12.4;

type Geometry = {
  features: {
    geometry: { type: string; coordinates: unknown };
    properties: { kind?: string; marker?: string; stop: number };
  }[];
};

// The run's geometry with a 12.4 km retrace of "Colle del Sommeiller" added (W4: the packaged planner's one-track run
// has none), read once and only fulfilled, as slice 12's withSommeillerRetrace.
function withSommeillerRetrace(answer: Geometry): Geometry {
  const track = answer.features.find((f) => f.properties.kind === "track")!;
  const [lon, lat] = (track.geometry.coordinates as [number, number][])[0];
  const degrees = RETRACE_KM / (111.32 * Math.cos((lat * Math.PI) / 180));
  const points = [0, 1, 2, 3, 4].map((i) => [
    lon - (degrees * i) / 4,
    lat + (i % 2 === 0 ? 0 : 0.004),
  ]);
  const stop = Math.max(...answer.features.map((f) => f.properties.stop)) + 1;
  const common = {
    item_id: "sommeiller",
    name: "Colle del Sommeiller",
    stop,
  };
  const retrace = {
    type: "Feature",
    geometry: { type: "LineString", coordinates: points },
    properties: {
      ...common,
      kind: "retrace",
      level: "unconfirmed",
      reason: null,
      geometry: "available",
    },
  };
  const end = {
    type: "Feature",
    geometry: { type: "Point", coordinates: points[4] },
    properties: { ...common, marker: "stop", end_stop: null },
  };
  const lines = answer.features.filter((f) => f.geometry.type === "LineString");
  const markers = answer.features.filter((f) => f.geometry.type === "Point");
  return {
    ...answer,
    features: [...lines, retrace, ...markers, end] as Geometry["features"],
  };
}

// Marco's trip, planned on the offline road map (an estimate): his own project, the Assietta trail, Torino as Start
// and End and a plan, all through the planner's own API (`page.request`), then the project's page, on Your route.
async function planOnTheOfflineMap(
  page: Page,
  testInfo: TestInfo,
): Promise<string> {
  const name = `Calm map (${testInfo.project.name} ${Date.now()})`;
  const created = (await (
    await page.request.post("/api/projects", { data: { name } })
  ).json()) as { id: string };
  const id = created.id;
  await page.request.post(`/api/projects/${id}/tracks`, {
    multipart: {
      files: {
        name: "assietta.gpx",
        mimeType: "application/gpx+xml",
        buffer: readFileSync(
          path.join(testInfo.project.testDir, ASSIETTA_FILE),
        ),
      },
    },
  });
  const torino = (await (
    await page.request.post(`/api/projects/${id}/pois`, {
      data: { name: HOME, lat: 45.0703, lon: 7.6869 },
    })
  ).json()) as { id: string };
  await page.request.put(`/api/projects/${id}/anchors`, {
    data: { start_item_id: torino.id, end_item_id: torino.id },
  });
  await page.request.post(`/api/projects/${id}/plan-runs`);
  await expect
    .poll(async () => (await readyRunIds(page, id)).length, {
      timeout: 120_000,
      message: "the planner's run is ready",
    })
    .toBe(1);
  await page.goto(`/#/projects/${id}`);
  await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible({
    timeout: 30_000,
  });
  return page.url();
}

// A real run, its map on show with the planner's hook for the map's own style (`?e2e=1`).
async function openTheMap(
  page: Page,
  testInfo: TestInfo,
  options: { retrace?: boolean } = {},
): Promise<Locator> {
  test.setTimeout(240_000);
  await serveTheBaseMap(page, testInfo);
  const projectUrl = await planOnTheOfflineMap(page, testInfo);
  if (options.retrace) {
    const geometry = /\/api\/plan-runs\/[^/]+\/geometry$/;
    const real = (await (
      await page.request.get(await geometryAddress(page, projectUrl))
    ).json()) as Geometry;
    const answer = withSommeillerRetrace(real);
    await page.route(geometry, (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: answer })
        : route.continue(),
    );
  }
  await page.goto(projectUrl.replace("/#/", "/?e2e=1#/"));
  const map = page.getByRole("region", { name: "Map of the run" });
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible({
    timeout: 60_000,
  });
  return map;
}

// The geometry address of the project's latest ready run, from the planner's own run list.
async function geometryAddress(
  page: Page,
  projectUrl: string,
): Promise<string> {
  const id = decodeURIComponent(/#\/projects\/([^/]+)$/.exec(projectUrl)![1]);
  const runs = (await (
    await page.request.get(`/api/projects/${id}/plan-runs`)
  ).json()) as { id: string; status: string }[];
  const ready = runs.filter((run) => run.status === "ready");
  return `/api/plan-runs/${ready[ready.length - 1].id}/geometry`;
}

type StyleLayer = {
  id: string;
  type: string;
  layout?: Record<string, unknown>;
  paint?: Record<string, unknown>;
};

// The map's own style as it stands now (its layers in drawing order); undefined while a style is being replaced.
async function layersOf(page: Page): Promise<StyleLayer[] | undefined> {
  return page.evaluate(() => {
    const map = (
      window as unknown as {
        __overlandRunMap?: { getStyle(): { layers: unknown[] } | undefined };
      }
    ).__overlandRunMap;
    try {
      return map?.getStyle()?.layers as never;
    } catch {
      return undefined;
    }
  });
}

// Waits until the light base map is the map's: its own layers are in the style, and the route after them.
async function layersWithTheBaseMap(page: Page): Promise<string[]> {
  await expect
    .poll(
      async () =>
        (await layersOf(page))?.some((l) => l.id === "place-labels") ?? false,
      { message: "the map adopts the light base map" },
    )
    .toBe(true);
  return (await layersOf(page))!.map((l) => l.id);
}

const terrainButton = (map: Locator): Locator =>
  map.getByRole("button", { name: "Terrain" });
const credit = (map: Locator): Locator =>
  map.locator(".maplibregl-ctrl-attrib");

async function config(page: Page): Promise<{
  tile_url: string;
  attribution: string;
  base_attribution: string;
}> {
  return (await page.request.get("/api/config/map")).json();
}

test("The map opens on a calm base map with its credit", async ({
  page,
}, testInfo) => {
  const map = await openTheMap(page, testInfo);
  const ids = await layersWithTheBaseMap(page);
  const base = CALM_STYLE.layers.map((layer) => layer.id);
  expect(ids.slice(0, base.length), "the base map's layers come first").toEqual(
    base,
  );
  for (const route of ROUTE_LAYERS)
    expect(ids.indexOf(route), `${route} is below the labels`).toBeGreaterThan(
      ids.indexOf("place-labels"),
    );
  const light = (await config(page)).base_attribution;
  await expect(credit(map)).toContainText(light.trim().slice(0, 20));
});

test("Terrain switches to the topographic map and back", async ({
  page,
}, testInfo) => {
  const map = await openTheMap(page, testInfo);
  const before = await layersWithTheBaseMap(page);
  const { attribution, base_attribution: light } = await config(page);
  const terrainCredit = attribution.split("|")[0].trim().slice(0, 20);
  const visibility = async (): Promise<unknown> =>
    (await layersOf(page))?.find((l) => l.id === "terrain")?.layout?.visibility;
  const button = terrainButton(map);

  await expect(button).toHaveAttribute("aria-pressed", "false");
  expect(await visibility()).toBe("none");
  await expect(credit(map)).toContainText(light.trim().slice(0, 20));

  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await expect.poll(visibility).toBe("visible");
  await expect(credit(map)).toContainText(terrainCredit);
  await expect(credit(map)).not.toContainText(light.trim().slice(0, 20));
  const on = (await layersOf(page))!.map((l) => l.id);
  expect(on.indexOf("terrain"), "above every base layer").toBeGreaterThan(
    on.indexOf("place-labels"),
  );
  expect(
    on.slice(on.indexOf("terrain") + 1),
    "the route, unchanged and last",
  ).toEqual(before.slice(before.indexOf(ROUTE_LAYERS[0]) - 1));

  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "false");
  await expect.poll(visibility).toBe("none");
  await expect(credit(map)).toContainText(light.trim().slice(0, 20));
  await expect(credit(map)).not.toContainText(terrainCredit);
});

// Two defects of 12-02 found on real tiles (2026-11-20).
// An alpha colour as the colour it shows on the map control's white.
const onWhite = (css: string): string => {
  const [r, g, b] = parseColour(css);
  const alpha = Number(
    /^rgba\(.*,\s*([\d.]+)\s*\)$/.exec(css.trim())?.[1] ?? 1,
  );
  const flat = [r, g, b].map((c) => Math.round(c * alpha + 255 * (1 - alpha)));
  return `rgb(${flat.join(", ")})`;
};

test("The pressed Terrain button keeps its text readable, hovered or not", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  const map = await openTheMap(page, testInfo);
  const button = terrainButton(map);
  const look = () =>
    button.evaluate((el) => {
      const style = getComputedStyle(el);
      return { colour: style.color, background: style.backgroundColor };
    });
  const resting = await look();

  await button.click(); // the pointer stays on it: the hover look is the one a user sees
  await expect(button).toHaveAttribute("aria-pressed", "true");
  const hovered = await look();
  expect(
    contrastRatio(hovered.colour, onWhite(hovered.background)),
    "pressed and hovered",
  ).toBeGreaterThanOrEqual(4.5);
  expect(
    onWhite(hovered.background),
    "a cue besides the attribute: the fill changes",
  ).not.toBe(onWhite(resting.background));

  await page.mouse.move(0, 0);
  const away = await look();
  expect(
    contrastRatio(away.colour, onWhite(away.background)),
    "pressed",
  ).toBeGreaterThanOrEqual(4.5);
});

test("The light map's credit names OpenFreeMap once", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "the laptop browser only");
  test.setTimeout(240_000);
  await serveTheBaseMap(page, testInfo);
  // A base map like OpenFreeMap's: its vector source is a TileJSON address that carries a credit of its own.
  const tileJson = "https://tiles.example.test/planet";
  const style = {
    ...CALM_STYLE,
    sources: {
      ...CALM_STYLE.sources,
      openmaptiles: { type: "vector", url: tileJson },
    },
    layers: [
      ...CALM_STYLE.layers,
      {
        id: "roads",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
      },
    ],
  };
  const { base_style_url: styleUrl } = (await (
    await page.request.get("/api/config/map")
  ).json()) as { base_style_url: string };
  await page.route(tileJson, (route) =>
    route.fulfill({
      json: {
        tilejson: "2.0.0",
        tiles: ["https://tiles.example.test/planet/{z}/{x}/{y}.pbf"],
        attribution:
          '<a href="https://openfreemap.org">OpenFreeMap</a> © OpenMapTiles Data from OpenStreetMap',
      },
    }),
  );
  await page.route(styleUrl, (route) => route.fulfill({ json: style }));
  const projectUrl = await planOnTheOfflineMap(page, testInfo);
  await page.goto(projectUrl.replace("/#/", "/?e2e=1#/"));
  const map = page.getByRole("region", { name: "Map of the run" });
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible({
    timeout: 60_000,
  });
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          (
            window as unknown as {
              __overlandRunMap?: { isSourceLoaded(id: string): boolean };
            }
          ).__overlandRunMap?.isSourceLoaded("openmaptiles"),
        ),
      { message: "the base map's own source, credit and all, is loaded" },
    )
    .toBe(true);
  await expect(credit(map)).toContainText(
    (await config(page)).base_attribution.trim().slice(0, 20),
  );
  await expect
    .poll(
      async () =>
        ((await credit(map).textContent()) ?? "").split("OpenFreeMap").length -
        1,
      {
        message: "the credit names OpenFreeMap once",
      },
    )
    .toBe(1);
});

for (const base of ["light base", "topographic"]) {
  test(`The route stands out on both base maps: ${base}`, async ({
    page,
  }, testInfo) => {
    const map = await openTheMap(page, testInfo, { retrace: true });
    await layersWithTheBaseMap(page);
    if (base === "topographic") await terrainButton(map).click();
    const layers = (await layersOf(page))!;
    const ids = layers.map((l) => l.id);
    const lastBaseLayer =
      ids.indexOf("terrain") > 0 ? "terrain" : "place-labels";
    for (const route of ROUTE_LAYERS) {
      const at = ids.indexOf(route);
      expect(ids[at - 1], `${route} has its casing directly below`).toBe(
        `${route}-casing`,
      );
      expect(
        at - 1,
        `${route} and its casing are after the base map`,
      ).toBeGreaterThan(ids.indexOf(lastBaseLayer));
      const casing = layers[at - 1].paint!["line-color"] as string;
      const line = layers[at].paint!["line-color"] as string;
      expect(
        contrastRatio(line, casing),
        `${route} stands out from its casing`,
      ).toBeGreaterThanOrEqual(3);
    }
    await expect
      .poll(
        () =>
          page.evaluate(
            () =>
              (
                window as unknown as {
                  __overlandRunMap: {
                    queryRenderedFeatures(o: { layers: string[] }): unknown[];
                  };
                }
              ).__overlandRunMap.queryRenderedFeatures({ layers: ["retrace"] })
                .length,
          ),
        { message: "the retrace is drawn" },
      )
      .toBeGreaterThan(0);
  });
}

test("Road, trail and retrace stay apart on both base maps", async ({
  page,
}, testInfo) => {
  const map = await openTheMap(page, testInfo, { retrace: true });
  await layersWithTheBaseMap(page);
  for (const topographic of [false, true]) {
    if (topographic) await terrainButton(map).click();
    const layers = (await layersOf(page))!;
    const paint = (id: string) => layers.find((l) => l.id === id)!.paint!;
    const colours = ["road-confirmed", "track", "retrace"].map(
      (id) => paint(id)["line-color"],
    );
    expect(new Set(colours).size, "three different colours").toBe(3);
    expect(
      paint("retrace")["line-dasharray"],
      "the retrace is dashed",
    ).toBeTruthy();
    expect(paint("track")["line-dasharray"]).toBeUndefined();
    expect(paint("road-confirmed")["line-dasharray"]).toBeUndefined();
  }
});

test("An estimate says so on the map on both base maps", async ({
  page,
}, testInfo) => {
  const map = await openTheMap(page, testInfo);
  const chip = map.getByRole("note", { name: ESTIMATE_NOTE });
  await expect(chip).toBeVisible();
  await expect(chip).toHaveText(/Estimate/);
  await terrainButton(map).click();
  await expect(terrainButton(map)).toHaveAttribute("aria-pressed", "true");
  await expect(chip).toBeVisible();
  await expect(chip).toHaveText(/Estimate/);
});

test("On a phone the map controls fit and can be tapped", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "webkit-iphone14",
    "the 390 px phone is checked on the phone profile",
  );
  const map = await openTheMap(page, testInfo);
  await layersWithTheBaseMap(page);
  await expect(credit(map)).toBeVisible();
  const chip = map.getByRole("note", { name: ESTIMATE_NOTE });
  await expect(chip).toBeVisible();
  await expect(terrainButton(map)).toBeVisible();
  const box = async (l: Locator) => (await l.boundingBox())!;
  const controls = {
    Terrain: await box(terrainButton(map)),
    Estimate: await box(chip),
    credit: await box(credit(map)),
  };
  const numbers = await map.locator(".run-marker.numbered").all();
  expect(numbers.length).toBeGreaterThan(1);
  const apart = (a: Box, b: Box): boolean =>
    a.x + a.width <= b.x ||
    b.x + b.width <= a.x ||
    a.y + a.height <= b.y ||
    b.y + b.height <= a.y;
  type Box = { x: number; y: number; width: number; height: number };
  const names = Object.keys(controls) as (keyof typeof controls)[];
  for (const [i, one] of names.entries())
    for (const other of names.slice(i + 1))
      expect(apart(controls[one], controls[other]), `${one} and ${other}`).toBe(
        true,
      );
  for (const number of numbers) {
    const at = await box(number);
    for (const name of names)
      expect(apart(controls[name], at), `${name} and a stop number`).toBe(true);
  }
  expect(controls.Terrain.width).toBeGreaterThanOrEqual(44);
  expect(controls.Terrain.height).toBeGreaterThanOrEqual(44);
});

test("The route still shows when the base map does not load", async ({
  page,
}, testInfo) => {
  const map = await openTheMap(page, testInfo);
  await layersWithTheBaseMap(page);
  const { tile_url: tiles } = await config(page);
  const terrainHost = new URL(tiles.split("{")[0]).origin;
  await page.route(
    (url) => url.origin === terrainHost,
    (route) => route.abort(),
  );
  const shown = async (): Promise<void> => {
    await expect(map.locator(".run-marker.numbered").first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible();
    await expect
      .poll(
        () =>
          page.evaluate(
            () =>
              (
                window as unknown as {
                  __overlandRunMap: {
                    queryRenderedFeatures(o: { layers: string[] }): unknown[];
                  };
                }
              ).__overlandRunMap.queryRenderedFeatures({ layers: ["track"] })
                .length,
          ),
        { message: "the route lines are drawn" },
      )
      .toBeGreaterThan(0);
  };
  // the Terrain tiles do not load: the light base map stays under them and the route over them
  await terrainButton(map).click();
  await expect(terrainButton(map)).toHaveAttribute("aria-pressed", "true");
  await shown();
  expect((await layersOf(page))!.some((l) => l.id === "place-labels")).toBe(
    true,
  );

  // the style does not load either: the route stays on the plain background
  const style = await styleAddress(page);
  await page.route(style, (route) => route.abort());
  await page.reload();
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible({
    timeout: 60_000,
  });
  await shown();
  expect((await layersOf(page))!.some((l) => l.id === "place-labels")).toBe(
    false,
  );
});

async function styleAddress(page: Page): Promise<string> {
  return (
    (await (await page.request.get("/api/config/map")).json()) as {
      base_style_url: string;
    }
  ).base_style_url;
}

// Used by the tests above once DELIVER writes them (kept here so the W4 rule is in one place from the start).
export const w4 = { answerWith, onRealRoads, expect };

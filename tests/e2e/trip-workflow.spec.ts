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
import path from "node:path";
import {
  expect,
  test,
  type Locator,
  type Page,
  type TestInfo,
} from "@playwright/test";
import { contrastRatio } from "./contrast";
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

// ===================== US-23 Build the trip, plan it, see the route =====================

test.fixme("A project without a route opens on Build the trip", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real: New project, Add -> Upload GPX trails (assietta.gpx), Add -> Type coordinates (Torino 45.0703, 7.6869).
  // Checks: phase "Build the trip", one list "Your trip" with both, badge "No plan yet", one main action
  // "Plan the route", no card, itinerary, "Export GPX" or "Details".
});

test.fixme("Every way to add a stop is in one Add control and lands in the one list", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real. Checks: "Add" offers "Upload GPX trails", "Click on the map", "Type coordinates"; Lago del Moncenisio
  // (45.2280, 6.9420) typed lands in the same list as the trail. The map is drawn before any route (D288).
});

test.fixme("Start and End are set on a place in the list", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real: the row menu of Torino, "Set as start" then "Set as end" (the anchors call once both are chosen).
  // Checks: Torino's row tags Start and End; the trail's row offers neither; no "Set Start and End" form.
});

test.fixme("While planning, the trip is read-only and nothing is exported", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // A real ready run (rewritten to real roads with answerWith/onRealRoads), a place added, then the POST answered
  // {job_id: "held-job", notices: []} and the job held at "solving", stoppable (W4, fulfill only).
  // Checks: "Planning…" with a progressbar; "Stop and use best so far" the only main action; list read-only, no
  // "Add"; no "Export GPX" link anywhere on the page (D208 F2).
});

test.fixme("Stopping shows the best route found so far", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Held job (W4); after "Stop and use best so far" the job answers done with the real run's id, whose detail is
  // rewritten with not_fully_optimised "stopped" and its line in `messages` (fulfill only).
  // Checks: "Your route", badge "Route ready"; the card's tag "Not fully optimised"; Details holds
  // "not fully optimised (stopped)" word for word, not in view while Details is closed (D285).
});

test.fixme("Edit trip goes back to building and the shown route goes out of date", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real ready run; "Edit trip", Add -> "Click on the map", a click, the name "Lago del Moncenisio", Add.
  // Checks: "Build the trip" with the place listed; badge "Out of date, plan again"; main action "Plan the route".
});

test.fixme("A refusal keeps Marco on Build the trip with the planner's own words", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real: the trail and a place, no Start; "Plan the route" is refused by the planner (422 missing_anchor).
  // Checks: "Set the Start before calculating" word for word; still "Build the trip"; the list unchanged.
});

// ===================== US-24 The route is the main result =====================

test.fixme("On a laptop the summary card and the first steps are in view", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  await page.setViewportSize({ width: 1440, height: 900 });
  // chromium only. Real run, detail rewritten to real roads (answerWith + onRealRoads).
  // Checks: "Your route"; the card with total km and time, road and off-road, "Real roads"; steps 1-3 boxes inside
  // the viewport without scrolling; main action "Export GPX", "Edit trip" offered.
});

test.fixme("An estimate route says Estimate in the card and on the map", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real plan on the offline road map; the download through "Export GPX".
  // Checks: "Estimate" in the card and on the map; no "Real roads"; the file is "<project>-run1-estimate.gpx" (D268).
});

test.fixme("Selecting a step moves the map to it", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real run on real roads (W4). Checks: after a press on step 3 the map's published centre and zoom move to that
  // stop's bounds; marker 3 has the accent ring and step 3 is highlighted; the other lines dimmed.
});

test.fixme("Selecting a stop on the map highlights its step", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Detail and geometry rewritten to the owner's order with Colle del Sommeiller as stop 7 (W4, fulfill only).
  // Checks: a press on marker 7 highlights step 7 and scrolls it into view.
});

test.fixme("A retrace is its own step, linked to its own line", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // A 12.4 km retrace of Colle del Sommeiller added to the detail and the geometry (W4, as slice 12's
  // withSommeillerRetrace, read once). Checks: the retrace step fits the map to the retrace line; its reason word for
  // word and 12.4 km off-road; the trail once as a trail step and once as a retrace step.
});

test.fixme("On a phone the map follows the selected step", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // webkit-iphone14 only. Real run on real roads (W4). Checks: a tap on step 5 scrolls the map into view, zoomed
  // to the stop with marker 5 highlighted; no sideways scroll; every step >= 44 px high.
});

// ===================== US-25 The status in user words, engine details behind Details =====================

for (const status of [
  "No plan yet",
  "Loading",
  "Planning…",
  "Route ready",
  "Couldn't plan",
  "Out of date, plan again",
]) {
  test.fixme(`Every status has its own words and look: ${status}`, async ({
    page,
  }, testInfo) => {
    await serveTheBaseMap(page, testInfo);
    // chromium. No plan yet, Route ready and Out of date: real. Loading: the run list held, then continued.
    // Planning: held job (W4). Couldn't plan: a failed run added to the run list read once (answerWith), with its
    // detail fulfilled. Checks: the badge reads the status; glyph, border and fill differ from every other status.
  });
}

test.fixme("Engine details wait behind one closed Details", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real memo reuse: the same trip planned twice; the run's `messages` and `provider_header` read with page.request.
  // Checks: "Plan run #N", the provider line, the run time line, the reuse line and "Re-optimise (ignore previous
  // result)" hidden; one closed Details; opened, all shown, the planner's lines verbatim and in its order.
});

test.fixme("Couldn't plan keeps the previous route and its export", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real ready run (rewritten to real roads); the run list read once with a failed next run added, its detail
  // fulfilled with the planner's time-limit words for that run (W4). Checks: badge "Couldn't plan" and the failure
  // words verbatim; the card headed "Previous route" with its itinerary; its Details names that run's number;
  // "Export GPX" downloads that run's own file (the planner's name, D268); no export or "Estimate" for the failed run.
});

test.fixme("Couldn't plan without an earlier route keeps Marco on Build the trip", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // No run; the POST answered with a job id and the job fulfilled as failed with the planner's
  // "Routing engine unreachable - nothing was changed. Try again later." (W4). Checks: "Couldn't plan" and the words
  // verbatim; still "Build the trip" with "Plan the route"; no "Export GPX".
});

test.fixme("An out-of-date route asks to be planned again and can still be exported", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real: a plan on the offline road map, then a place added. Checks: "Out of date, plan again" and "Estimate" in
  // the card; the route stays with "Plan the route" as the main action; "Export GPX" still offered, the planner's
  // "-estimate.gpx" name for that run.
});

test.fixme("Planning an unchanged trip with a retrace reuses the route and keeps each stop once", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real memo reuse ("Edit trip", "Plan the route" unchanged); the retrace added to both runs' answers (W4).
  // Checks: "Route ready"; the trail once and its retrace once; Details holds the planner's reuse line for the run
  // it reused and offers "Re-optimise (ignore previous result)".
});

test.fixme("The planner's notices stay in view", async ({ page }, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // The POST answered {job_id: "held-job", notices: ["Large project - calculation may take longer than 3
  // minutes"]} and the job held (W4). Checks: the notice word for word, outside Details.
});

// ===================== US-26 A calm map on which the route stands out =====================

const ASSIETTA =
  "../acceptance/overland_route_planner_mvp/fixtures/gpx/assietta.gpx";
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
// and End, "Calculate" (the page of this step; 12-03 and later change these controls).
async function planOnTheOfflineMap(
  page: Page,
  testInfo: TestInfo,
): Promise<string> {
  const name = `Calm map (${testInfo.project.name} ${Date.now()})`;
  await page.goto("/");
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "New project" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await page
    .getByLabel("GPX files")
    .setInputFiles(path.join(testInfo.project.testDir, ASSIETTA));
  await page.getByRole("button", { name: "Import" }).click();
  const items = page.getByRole("list", { name: "Items" });
  await expect(items.getByRole("listitem")).toHaveCount(1);
  await page.getByLabel("Place name").fill(HOME);
  await page.getByLabel("Latitude").fill("45.0703");
  await page.getByLabel("Longitude").fill("7.6869");
  await page.getByRole("button", { name: "Add place" }).click();
  await expect(items.getByRole("listitem")).toHaveCount(2);
  await page.getByLabel("Start", { exact: true }).selectOption({ label: HOME });
  await page.getByLabel("End", { exact: true }).selectOption({ label: HOME });
  await page.getByRole("button", { name: "Set Start and End" }).click();
  await page.getByRole("button", { name: "Calculate" }).click();
  await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible({
    timeout: 120_000,
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

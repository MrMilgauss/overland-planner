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
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { serveBlankTiles } from "./blankTile";

const POSITRON = "https://tiles.openfreemap.org/styles/positron";

// The light base map as the tests serve it: a pale background and an empty label layer (no glyph is ever asked for:
// the layer has nothing to draw). The planner's route layers must come after both (D287 `transformStyle`).
const CALM_STYLE = {
  version: 8,
  name: "test light base map",
  glyphs: "https://tiles.example.test/fonts/{fontstack}/{range}.pbf",
  sources: {
    places: {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    },
  },
  layers: [
    {
      id: "background",
      type: "background",
      paint: { "background-color": "#f2f2ef" },
    },
    {
      id: "place-labels",
      type: "symbol",
      source: "places",
      layout: { "text-field": ["get", "name"] },
    },
  ],
};

// Blank tiles for every foreign host, then the light base map's style address answered with CALM_STYLE. The address
// is the planner's own answer (read once); before DELIVER adds `base_style_url` the default address stands in.
async function serveTheBaseMap(page: Page, testInfo: TestInfo): Promise<void> {
  await serveBlankTiles(
    page,
    testInfo.project.use.baseURL ?? "http://127.0.0.1:8080",
  );
  const config = (await (await page.request.get("/api/config/map")).json()) as {
    base_style_url?: string;
  };
  const style = config.base_style_url ?? POSITRON;
  await page.route(style, (route) => route.fulfill({ json: CALM_STYLE }));
}

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
  provider_header:
    "Provider: Valhalla (map data 2026-11-18) / profile: 4x4",
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

test.fixme("Selecting a step moves the map to it", async ({ page }, testInfo) => {
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

test.fixme("The map opens on a calm base map with its credit", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real run. Checks: the map's style holds CALM_STYLE's layers below the route; the credit control shows the
  // planner's `base_attribution`.
});

test.fixme("Terrain switches to the topographic map and back", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real run. Checks: "Terrain" (aria-pressed) makes the raster layer visible with its own credit, the route layers
  // unchanged and still last; pressed again, hidden and the light credit back.
});

for (const base of ["light base", "topographic"]) {
  test.fixme(`The route stands out on both base maps: ${base}`, async ({
    page,
  }, testInfo) => {
    await serveTheBaseMap(page, testInfo);
    // Real run, the retrace added (W4). Checks: each route line has a casing layer below it and both after every
    // base layer (labels included); line vs casing colour >= 3:1 with tests/e2e/contrast.ts.
  });
}

test.fixme("Road, trail and retrace stay apart on both base maps", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real run, the retrace added (W4). Checks on each base map: three different line colours; the retrace dashed.
});

test.fixme("An estimate says so on the map on both base maps", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real offline-road-map run. Checks: the map's "Estimate" chip with and without "Terrain".
});

test.fixme("On a phone the map controls fit and can be tapped", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // webkit-iphone14 only. Real estimate run. Checks: "Terrain", the chip and the credit boxes overlap neither each
  // other nor a stop number; "Terrain" >= 44 x 44 px.
});

test.fixme("The route still shows when the base map does not load", async ({
  page,
}, testInfo) => {
  await serveTheBaseMap(page, testInfo);
  // Real run; the Terrain tile host answered with route.abort() (and, a second check, the style address too).
  // Checks: after "Terrain" the route lines, the stop numbers and the itinerary are still shown.
});

// Used by the tests above once DELIVER writes them (kept here so the W4 rule is in one place from the start).
export const w4 = { answerWith, onRealRoads, expect };

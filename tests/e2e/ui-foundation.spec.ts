// Slice 12 UI foundation (US-20, US-21, US-22): the @ui scenarios of
// tests/acceptance/overland_route_planner_mvp/slice-12-ui-foundation.feature, one test per scenario (one per row of
// the plan-state outline), named after it. Every test blocks in CI job 7 (step 11-08).
//
// Runs in CI job 7 on chromium (Desktop Chrome; 1440 and 768 px set per test with `page.setViewportSize`) and
// webkit-iphone14 (390 px) against the packaged planner on PLANNER_URL, which plans on the offline road map.
// A test meant for one width skips itself on the other project (`test.skip(testInfo.project.name !== ...)`).
// Seeding follows workspace.spec.ts and run-map.spec.ts: the page itself (New project, Import assietta.gpx, Add place,
// Set Start and End, Calculate), `page.request` to the planner's own API, and blank tiles (`serveBlankTiles`).
// Each test creates its own project (both projects run at once against one planner).
// States the packaged planner cannot reach on its own are set by rewriting the planner's answer in this browser
// (`page.route`, policy waiver W4): Loading (held answer), Planning (job held at running), Failed run #5, a Valhalla
// run (`estimate: false`), a retrace, and the Diagnostics K2 count. Contrast: a small WCAG ratio helper in tests/e2e.
import path from "node:path";
import {
  devices,
  expect,
  test,
  type Locator,
  type Page,
  type TestInfo,
} from "@playwright/test";
import { expression, latest } from "@maplibre/maplibre-gl-style-spec";
import { serveBlankTiles } from "./blankTile";
import { contrastRatio, parseColour, readColours } from "./contrast";

const ASSIETTA =
  "../acceptance/overland_route_planner_mvp/fixtures/gpx/assietta.gpx";
const HOME = "Casa Marco, Torino";

// Marco's project, planned: his own project (both browser projects run at once), the Assietta trail, a start and end,
// and a plan on the offline road map. Returns the project's address.
async function makeAPlannedProject(
  page: Page,
  testInfo: TestInfo,
): Promise<string> {
  await serveBlankTiles(
    page,
    testInfo.project.use.baseURL ?? "http://127.0.0.1:8080",
  );
  const name = `Alpi Occidentali giugno 2027 (${testInfo.project.name} ${Date.now()})`;
  await page.goto("/");
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "New project" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await page
    .getByLabel("GPX files")
    .setInputFiles(path.join(testInfo.project.testDir, ASSIETTA));
  await page.getByRole("button", { name: "Import" }).click();
  await expect(
    page.getByRole("list", { name: "Items" }).getByRole("listitem"),
  ).toHaveCount(1);
  await page.getByLabel("Place name").fill(HOME);
  await page.getByLabel("Latitude").fill("45.0703");
  await page.getByLabel("Longitude").fill("7.6869");
  await page.getByRole("button", { name: "Add place" }).click();
  await expect(
    page.getByRole("list", { name: "Items" }).getByRole("listitem"),
  ).toHaveCount(2);
  await page.getByLabel("Start", { exact: true }).selectOption({ label: HOME });
  await page.getByLabel("End", { exact: true }).selectOption({ label: HOME });
  await page.getByRole("button", { name: "Set Start and End" }).click();
  await page.getByRole("button", { name: "Calculate" }).click();
  await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible({
    timeout: 120_000,
  });
  return page.url();
}

// ===================== US-20 One product: map first, one look, on any screen =====================

// "Plan run #4" is reached as Marco reaches it: the same project is Calculated four times on the offline road map
// (makeAPlannedProject presses Calculate once, three more presses follow); the planner's own run list says when the
// fourth run is ready, so the test never reads the page's wording of the run.
async function makeRunFour(page: Page, testInfo: TestInfo): Promise<string> {
  return makeRuns(page, testInfo, 4);
}

async function makeRuns(
  page: Page,
  testInfo: TestInfo,
  runs: number,
): Promise<string> {
  const projectUrl = await makeAPlannedProject(page, testInfo);
  const projectId = decodeURIComponent(
    /#\/projects\/([^/]+)$/.exec(projectUrl)![1],
  );
  const readyRuns = async (): Promise<number> => {
    const runs = (await (
      await page.request.get(`/api/projects/${projectId}/plan-runs`)
    ).json()) as {
      status: string;
    }[];
    return runs.filter((run) => run.status === "ready").length;
  };
  for (let ready = 1; ready < runs; ready += 1) {
    await page.getByRole("button", { name: "Calculate" }).click();
    await expect.poll(readyRuns, { timeout: 120_000 }).toBe(ready + 1);
    await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible({
      timeout: 30_000,
    });
  }
  return projectUrl;
}

type Box = { x: number; y: number; width: number; height: number };

async function boxOf(locator: Locator): Promise<Box> {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  if (!box) throw new Error("the element has no box on the page");
  return box;
}

// Every visible button, link, input and select of the page with a box smaller than 44 x 44 px (the map's attribution
// excluded), as text.
async function smallTargets(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const found: string[] = [];
    for (const el of document.querySelectorAll(
      "button, a[href], input, select",
    )) {
      if (el.closest(".maplibregl-ctrl-attrib")) continue;
      const style = getComputedStyle(el);
      const box = el.getBoundingClientRect();
      if (style.visibility === "hidden" || style.display === "none") continue;
      if (box.width === 0 && box.height === 0) continue;
      if (box.width < 43.5 || box.height < 43.5) {
        const name = el.getAttribute("aria-label") ?? el.textContent ?? el.id;
        found.push(
          `${el.tagName.toLowerCase()} "${name.trim().slice(0, 30)}" ${box.width.toFixed(0)}x${box.height.toFixed(0)}`,
        );
      }
    }
    return found;
  });
}

const scrollsSideways = (page: Page): Promise<boolean> =>
  page.evaluate(
    () =>
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth,
  );

// ===================== US-20 One product: map first, one look, on any screen =====================

test("On a laptop the map is the main surface", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium",
    "the laptop width is checked on the desktop browser",
  );
  test.setTimeout(300_000);
  await page.setViewportSize({ width: 1440, height: 900 });

  const projectUrl = await makeRunFour(page, testInfo);
  await page.goto(projectUrl);
  await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible({
    timeout: 30_000,
  });

  const map = await boxOf(page.getByRole("region", { name: "Map of the run" }));
  for (const group of ["Plan", "Items", "Start and end"]) {
    const region = await boxOf(
      page.getByRole("region", { name: group, exact: true }),
    );
    expect(
      map.width,
      `the map is wider than the ${group} group`,
    ).toBeGreaterThan(region.width);
  }
  const viewport = page.viewportSize()!;
  const inView = [
    page.getByRole("heading", { name: "Plan", exact: true }),
    page.getByRole("list", { name: "Itinerary" }),
    page.getByLabel("Totals"),
  ];
  for (const part of inView) {
    const box = await boxOf(part);
    expect(box.x, "right of the map").toBeGreaterThanOrEqual(
      map.x + map.width - 1,
    );
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y).toBeLessThan(viewport.height); // the top of the itinerary and of the totals is in the window
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
  }
});

test("On a phone nothing scrolls sideways and every target is touch-sized", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "webkit-iphone14",
    "the phone profile only",
  );
  test.setTimeout(300_000);

  const projectUrl = await makeRunFour(page, testInfo);
  for (const [where, address] of [
    ["home", "/"],
    ["project", projectUrl],
    ["Diagnostics", "/#/diagnostics"],
  ] as const) {
    await page.goto(address);
    if (where === "project")
      await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible({
        timeout: 30_000,
      });
    else await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await scrollsSideways(page), `${where} scrolls sideways`).toBe(
      false,
    );
    if (where === "project") {
      const map = await boxOf(
        page.getByRole("region", { name: "Map of the run" }),
      );
      const itinerary = await boxOf(
        page.getByRole("list", { name: "Itinerary" }),
      );
      expect(
        itinerary.y,
        "the itinerary is below the map",
      ).toBeGreaterThanOrEqual(map.y + map.height - 1);
    }
    expect(
      await smallTargets(page),
      `targets under 44 x 44 px on ${where}`,
    ).toEqual([]);
  }
});

test("At tablet width nothing overlaps", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium",
    "the tablet width is checked on the desktop browser",
  );
  test.setTimeout(300_000);
  await page.setViewportSize({ width: 768, height: 1024 });

  const projectUrl = await makeRunFour(page, testInfo);
  await page.goto(projectUrl);
  await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(
    page.getByRole("region", { name: "Map of the run" }),
  ).toBeVisible();

  // Controls, labels, headings and panels (the map's own widgets aside); an element and its own ancestors do not count.
  const overlaps = await page.evaluate(() => {
    const parts = [
      ...document.querySelectorAll(
        "button, a[href], input, select, label, h1, h2, h3, section, header, nav, ol, dl",
      ),
    ].filter((el) => {
      const box = el.getBoundingClientRect();
      return !el.closest(".maplibregl-map") && box.width > 0 && box.height > 0;
    });
    const name = (el: Element): string =>
      `${el.tagName.toLowerCase()} "${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 25)}"`;
    const found: string[] = [];
    for (const [i, a] of parts.entries()) {
      for (const b of parts.slice(i + 1)) {
        if (a.contains(b) || b.contains(a)) continue;
        const [p, q] = [a.getBoundingClientRect(), b.getBoundingClientRect()];
        const across = Math.min(p.right, q.right) - Math.max(p.left, q.left);
        const down = Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top);
        if (across > 1 && down > 1) found.push(`${name(a)} over ${name(b)}`);
      }
    }
    return found;
  });
  expect(overlaps).toEqual([]);
  expect(await scrollsSideways(page), "the page scrolls sideways").toBe(false);
});

test("Every page uses the same look and the controls are grouped by task", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium",
    "the look is checked on the desktop browser",
  );
  test.setTimeout(120_000);

  const name = `Alpi Occidentali giugno 2027 (${testInfo.project.name} ${Date.now()})`;
  await page.goto("/");
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "New project" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  const projectUrl = page.url();

  for (const [where, address] of [
    ["home", "/"],
    ["project", projectUrl],
    ["Diagnostics", "/#/diagnostics"],
  ] as const) {
    await page.goto(address);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const strays = await page.evaluate(() => {
      // The token values as the browser computes them, read through probes that use the tokens.
      const probe = document.createElement("div");
      probe.style.cssText =
        "font-size: var(--text-base); border-radius: var(--radius-sm); border-top-left-radius: var(--radius-sm)";
      const probeButton = document.createElement("div");
      probeButton.style.cssText = "border-radius: var(--radius-md)";
      document.body.append(probe, probeButton);
      const size = getComputedStyle(probe).fontSize;
      const smallRadius = getComputedStyle(probe).borderTopLeftRadius;
      const bigRadius = getComputedStyle(probeButton).borderTopLeftRadius;
      probe.remove();
      probeButton.remove();
      const found: string[] = [];
      for (const el of document.querySelectorAll(
        "button, input, select, a[href]",
      )) {
        if (el.closest(".maplibregl-map")) continue;
        const style = getComputedStyle(el);
        if (style.display === "none") continue;
        const isField = el.matches("input, select");
        const isLink = el.matches("a:not(.button)");
        const label = `${el.tagName.toLowerCase()} "${(el.getAttribute("aria-label") ?? el.textContent ?? el.id).trim().slice(0, 25)}"`;
        if (style.fontSize !== size)
          found.push(`${label} font ${style.fontSize}`);
        if (isLink) continue;
        const radius = isField ? smallRadius : bigRadius;
        if (style.borderTopLeftRadius !== radius)
          found.push(`${label} radius ${style.borderTopLeftRadius}`);
        if (
          style.borderTopWidth !== "1px" ||
          style.borderTopStyle === "none" ||
          style.borderTopStyle === "inset" ||
          style.borderTopStyle === "outset"
        )
          found.push(
            `${label} border ${style.borderTopWidth} ${style.borderTopStyle}`,
          );
      }
      return found;
    });
    expect(strays, `controls on ${where} that keep the browser's look`).toEqual(
      [],
    );
  }

  await page.goto(projectUrl);
  const order: number[] = [];
  for (const group of ["Plan", "Items", "Start and end"]) {
    const heading = page.getByRole("heading", { name: group, exact: true });
    order.push((await boxOf(heading)).y);
  }
  expect(
    order,
    "the groups follow one another: Plan, Items, Start and end",
  ).toEqual([...order].sort((a, b) => a - b));
});

test("The theme follows the system and text stays readable outdoors", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium",
    "one browser is enough for the colours",
  );
  test.setTimeout(180_000);

  // The helper itself, against known pairs: black on white, and two pairs of the D265 table.
  expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 1);
  expect(contrastRatio("#1d4ed8", "#ffffff")).toBeCloseTo(6.7, 1);
  expect(contrastRatio("#e6e8eb", "#121417")).toBeCloseTo(15.0, 1);

  const projectUrl = await makeAPlannedProject(page, testInfo);
  await page.goto(projectUrl);
  await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible({
    timeout: 30_000,
  });

  for (const scheme of ["dark", "light"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    const token = await page.evaluate(() =>
      getComputedStyle(document.documentElement)
        .getPropertyValue("--color-bg")
        .trim(),
    );
    expect(token, `--color-bg is defined in the ${scheme} look`).toMatch(
      /^#[0-9a-f]{3,6}$/i,
    );
    const body = await page.evaluate(
      () => getComputedStyle(document.body).backgroundColor,
    );
    expect(
      parseColour(body),
      `the ${scheme} page background is the token`,
    ).toEqual(parseColour(token));

    const texts = await readColours(page, "text");
    expect(texts.length).toBeGreaterThan(20);
    const weak = texts
      .map((t) => ({ ...t, ratio: contrastRatio(t.colour, t.background) }))
      .filter((t) => t.ratio < 4.5)
      .map(
        (t) =>
          `${t.text.slice(0, 40)} ${t.colour} on ${t.background} = ${t.ratio.toFixed(2)}`,
      );
    expect(weak, `text under 4.5:1 in the ${scheme} look`).toEqual([]);
  }
});

test("Keyboard focus is always visible", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium",
    "keyboard focus is checked on the desktop browser",
  );
  test.setTimeout(180_000);

  const projectUrl = await makeAPlannedProject(page, testInfo);
  await page.goto(projectUrl);
  const exportGpx = page.getByRole("link", { name: "Export GPX" });
  await expect(exportGpx).toBeVisible({ timeout: 30_000 });

  await page.keyboard.press("Tab"); // keyboard use is on; from here focus() shows a focus ring as Tab does
  await page.getByRole("button", { name: "Calculate" }).focus();
  const seen: string[] = [];
  for (let step = 0; step < 12; step += 1) {
    const look = await readColours(page, "focus");
    seen.push(look.element);
    expect(look.outlineStyle, `${look.element} has an outline`).not.toBe(
      "none",
    );
    expect(
      look.outlineWidth,
      `${look.element} outline width`,
    ).toBeGreaterThanOrEqual(2);
    expect(
      contrastRatio(look.outlineColour, look.background),
      `${look.element} outline against the page`,
    ).toBeGreaterThanOrEqual(3);
    if (await exportGpx.evaluate((el) => el === document.activeElement)) break;
    await page.keyboard.press("Tab");
  }
  expect(seen.at(-1)).toContain("Export GPX");
});

// The run's geometry with a 12.4 km retrace of "Colle del Sommeiller" added (W4: the packaged planner's one-track run
// has none): a line of five points west of the track's entry, and its numbered stop at the far end.
const RETRACE_KM = 12.4;

type Geometry = {
  features: {
    geometry: { type: string; coordinates: unknown };
    properties: { kind?: string; marker?: string; stop: number };
  }[];
};

function withSommeillerRetrace(answer: Geometry): Geometry {
  const track = answer.features.find((f) => f.properties.kind === "track")!;
  const [lon, lat] = (track.geometry.coordinates as [number, number][])[0];
  const degrees = RETRACE_KM / (111.32 * Math.cos((lat * Math.PI) / 180));
  const points = [0, 1, 2, 3, 4].map((i) => [
    lon - (degrees * i) / 4,
    lat + (i % 2 === 0 ? 0 : 0.004),
  ]);
  const stop = Math.max(...answer.features.map((f) => f.properties.stop)) + 1;
  const retrace = {
    type: "Feature",
    geometry: { type: "LineString", coordinates: points },
    properties: {
      kind: "retrace",
      stop,
      item_id: "sommeiller",
      name: "Colle del Sommeiller",
      level: "unconfirmed",
      reason: null,
      geometry: "available",
    },
  };
  const end = {
    type: "Feature",
    geometry: { type: "Point", coordinates: points[4] },
    properties: {
      marker: "stop",
      stop,
      item_id: "sommeiller",
      name: "Colle del Sommeiller",
      end_stop: null,
    },
  };
  const lines = answer.features.filter((f) => f.geometry.type === "LineString");
  const markers = answer.features.filter((f) => f.geometry.type === "Point");
  return {
    ...answer,
    features: [...lines, retrace, ...markers, end] as Geometry["features"],
  };
}

type MapLook = {
  zoom: number;
  iconSize: unknown;
  spacing: unknown;
  stopNumbers: number;
  arrowsOnStopNumbers: number;
  label: Box | undefined;
  labelOnStopNumber: boolean;
};

// What the map shows now: the zoom, the arrow layer's settings, and (from the rendered features and the boxes of the
// page's own markers) what covers a stop number.
const lookAtMap = (page: Page): Promise<MapLook> =>
  page.evaluate(() => {
    type Rendered = {
      getZoom(): number;
      getLayoutProperty(layer: string, name: string): unknown;
      queryRenderedFeatures(
        box: number[][],
        options: { layers: string[] },
      ): unknown[];
    };
    const map = (window as unknown as { __overlandRunMap: Rendered })
      .__overlandRunMap;
    const canvas = document
      .querySelector("canvas.maplibregl-canvas")!
      .getBoundingClientRect();
    const shown = (el: Element): DOMRect | undefined => {
      const style = getComputedStyle(el);
      return style.display === "none" || style.visibility === "hidden"
        ? undefined
        : el.getBoundingClientRect();
    };
    const numbers = [...document.querySelectorAll(".run-marker.numbered")]
      .map(shown)
      .filter((box): box is DOMRect => box !== undefined);
    const arrows = numbers.filter(
      (b) =>
        map.queryRenderedFeatures(
          [
            [b.left - canvas.left, b.top - canvas.top],
            [b.right - canvas.left, b.bottom - canvas.top],
          ],
          { layers: ["track-arrows"] },
        ).length > 0,
    );
    const element = document.querySelector(".run-marker.retrace");
    const label = element ? shown(element) : undefined;
    const meets = (a: DOMRect, b: DOMRect): boolean =>
      a.left < b.right &&
      b.left < a.right &&
      a.top < b.bottom &&
      b.top < a.bottom;
    return {
      zoom: map.getZoom(),
      iconSize: map.getLayoutProperty("track-arrows", "icon-size"),
      spacing: map.getLayoutProperty("track-arrows", "symbol-spacing"),
      stopNumbers: numbers.length,
      arrowsOnStopNumbers: arrows.length,
      label: label && {
        x: label.x,
        y: label.y,
        width: label.width,
        height: label.height,
      },
      labelOnStopNumber: label ? numbers.some((n) => meets(label, n)) : false,
    };
  });

// A layout setting as the map evaluates it at a zoom (its own expression evaluator; absent = 1 and 0, the defaults).
function settingAt(
  name: "icon-size" | "symbol-spacing",
  value: unknown,
  zoom: number,
): number {
  const fallback = name === "icon-size" ? 1 : 250;
  if (value === undefined) return fallback;
  const made = expression.createPropertyExpression(
    value,
    name,
    latest.layout_symbol[name],
  );
  if (made.result !== "success")
    throw new Error(`${name} is not an expression`);
  return made.value.evaluate({ zoom } as never) as number;
}

test("The map stays readable on a phone at trip-wide zoom", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "webkit-iphone14",
    "the 390 px phone is checked on the phone profile",
  );
  test.setTimeout(240_000);

  const projectUrl = await makeAPlannedProject(page, testInfo);
  await page.route(/\/api\/plan-runs\/[^/]+\/geometry$/, async (route) => {
    const answer = await route.fetch();
    await route.fulfill({
      response: answer,
      json: withSommeillerRetrace((await answer.json()) as Geometry),
    });
  });
  await page.goto(projectUrl.replace("/#/", "/?e2e=1#/"));
  const map = page.getByRole("region", { name: "Map of the run" });
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible({
    timeout: 60_000,
  });
  await expect(map.locator(".run-marker.retrace")).toHaveCount(1);
  await expect
    .poll(async () => (await lookAtMap(page)).stopNumbers, {
      message: "the stop numbers are on the map",
    })
    .toBeGreaterThan(1);

  // The whole trip.
  const wide = await lookAtMap(page);
  const wideSize = settingAt("icon-size", wide.iconSize, wide.zoom);
  expect(wide.arrowsOnStopNumbers, "no arrow covers a stop number").toBe(0);
  expect(
    wide.labelOnStopNumber,
    "the retrace label covers no stop number",
  ).toBe(false);

  // Zoomed in to the trail (the map's own Zoom in control: a phone has no wheel here).
  const zoomIn = map.getByRole("button", { name: "Zoom in" });
  for (let tries = 0; tries < 8; tries += 1) {
    const before = (await lookAtMap(page)).zoom;
    if (before >= 13) break;
    await zoomIn.click();
    await expect
      .poll(async () => (await lookAtMap(page)).zoom, {
        message: "the map zooms in",
      })
      .toBeGreaterThan(before + 0.5);
  }
  await expect
    .poll(async () => (await lookAtMap(page)).labelOnStopNumber, {
      message: "the retrace label covers no stop number once zoomed in",
    })
    .toBe(false);
  const close = await lookAtMap(page);
  expect(close.zoom).toBeGreaterThanOrEqual(13);
  expect(
    close.arrowsOnStopNumbers,
    "no arrow covers a stop number, zoomed in",
  ).toBe(0);
  expect(
    wideSize,
    `arrows at the trip-wide view (zoom ${wide.zoom.toFixed(1)}) are smaller than on the trail (zoom ${close.zoom.toFixed(1)})`,
  ).toBeLessThan(settingAt("icon-size", close.iconSize, close.zoom));
  expect(
    settingAt("symbol-spacing", wide.spacing, wide.zoom),
    "the arrows are spaced wider apart when zoomed out",
  ).toBeGreaterThan(settingAt("symbol-spacing", close.spacing, close.zoom));
});

// ===================== US-21 Plan state and whether its roads are real =====================

type StateLook = { glyph: string; border: string; fill: string };

// The D266 table: what each state shows besides its colour. Two states never share glyph, border style and fill.
const STATE_LOOKS: Record<string, StateLook> = {
  "No plan yet": { glyph: "", border: "dashed", fill: "outline" },
  Loading: { glyph: "", border: "solid", fill: "outline" },
  Planning: { glyph: "", border: "solid", fill: "filled" },
  "Plan run #6": { glyph: "\u2713", border: "solid", fill: "filled" },
  Failed: { glyph: "\u2715", border: "solid", fill: "filled" },
  Stale: { glyph: "!", border: "solid", fill: "filled" },
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

async function expectState(page: Page, label: string): Promise<void> {
  const own = STATE_LOOKS[label];
  const looks = Object.values(STATE_LOOKS).map((l) => JSON.stringify(l));
  expect(
    new Set(looks).size,
    "no two states share glyph, border and fill",
  ).toBe(looks.length);
  await expect(stateBadge(page)).toHaveCount(1);
  await expect(stateBadge(page)).toBeVisible();
  await expect
    .poll(() => badgeLook(stateBadge(page)))
    .toEqual({ label, ...own });
}

// Planning without a real solve: the planner's answer to Calculate and to the job is rewritten (W4), the job held at
// "solving" and stoppable.
async function holdPlanning(page: Page): Promise<void> {
  await page.route(/\/api\/projects\/[^/]+\/plan-runs$/, async (route) => {
    if (route.request().method() === "POST")
      await route.fulfill({ status: 202, json: { job_id: "held-job" } });
    else await route.continue();
  });
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

async function makeAnEmptyProject(
  page: Page,
  testInfo: TestInfo,
): Promise<void> {
  await serveBlankTiles(
    page,
    testInfo.project.use.baseURL ?? "http://127.0.0.1:8080",
  );
  const name = `Alpi Occidentali giugno 2027 (${testInfo.project.name} ${Date.now()})`;
  await page.goto("/");
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "New project" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

const FAILED_WORDS =
  "No valid route found within the time limit - plan run #5 failed";

for (const label of Object.keys(STATE_LOOKS)) {
  test(`Every plan state has its own label and look: ${label}`, async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name !== "chromium",
      "the look is checked on the desktop browser",
    );
    test.setTimeout(300_000);

    if (label === "No plan yet") {
      await makeAnEmptyProject(page, testInfo);
    } else if (label === "Loading") {
      await makeAnEmptyProject(page, testInfo);
      const projectUrl = page.url();
      let release: () => void = () => {};
      const held = new Promise<void>((done) => (release = done));
      await page.route(/\/api\/projects\/[^/]+\/plan-runs$/, async (route) => {
        await held;
        await route.continue();
      });
      await page.goto("/");
      await page.goto(projectUrl);
      await expectState(page, label);
      await expect(stateBadge(page)).toHaveAttribute("aria-busy", "true");
      release();
      await expect(stateBadge(page)).toContainText("No plan yet");
      return;
    } else if (label === "Planning") {
      await makeAnEmptyProject(page, testInfo);
      await holdPlanning(page);
      await page.getByRole("button", { name: "Calculate" }).click();
    } else if (label === "Plan run #6") {
      await makeRuns(page, testInfo, 6);
    } else if (label === "Failed") {
      await makeRunFour(page, testInfo);
      await failRunFive(page);
      await page.reload();
    } else {
      await makeRunFour(page, testInfo);
      await page.getByLabel("Place name").fill("Rifugio Selleries");
      await page.getByLabel("Latitude").fill("45.0123");
      await page.getByLabel("Longitude").fill("7.0456");
      await page.getByRole("button", { name: "Add place" }).click();
      await expect(
        page.getByRole("list", { name: "Items" }).getByRole("listitem"),
      ).toHaveCount(3);
      await page.reload();
      await expect(
        page.getByText("Plan run #4", { exact: true }),
      ).toBeVisible();
    }
    await expectState(page, label);
  });
}

// Plan run #5 failed on its time limit, as the planner words it: the run list and that run's detail are rewritten (W4),
// every other answer is the planner's own.
async function failRunFive(page: Page): Promise<void> {
  await page.route(/\/api\/projects\/[^/]+\/plan-runs$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const runs = (await response.json()) as object[];
    await route.fulfill({
      response,
      json: [
        ...runs,
        { id: "failed-run-5", number: 5, status: "failed", stale: false },
      ],
    });
  });
  await page.route(/\/api\/plan-runs\/failed-run-5$/, (route) =>
    route.fulfill({
      json: {
        id: "failed-run-5",
        project_id: "p",
        number: 5,
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
}

test("While planning, Stop is offered", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium",
    "the planning state is checked on the desktop browser",
  );
  test.setTimeout(120_000);
  await makeAnEmptyProject(page, testInfo);
  await holdPlanning(page);
  await page.getByRole("button", { name: "Calculate" }).click();
  await expectState(page, "Planning");
  await expect(
    page.getByRole("button", { name: "Stop and use best so far" }),
  ).toBeVisible();
});

test("A Failed run shows the label Failed and the planner's own words", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium",
    "the failed state is checked on the desktop browser",
  );
  test.setTimeout(300_000);
  await makeRunFour(page, testInfo);
  await failRunFive(page);
  await page.reload();

  await expectState(page, "Failed");
  await expect(
    page.getByRole("alert").filter({ hasText: FAILED_WORDS }),
  ).toBeVisible();
  await expect(page.getByText("Plan run #4", { exact: true })).toBeVisible();
  // plan run #5 offers no export; the older run #4 keeps its own, named with its number (D208, D276)
  await expect(
    page.getByRole("link", { name: "Export GPX of plan run #5" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Export GPX of plan run #4" }),
  ).toBeVisible();
  // the Failed run carries no estimate marker; run #4 is the real offline-road-map run, so its own pill shows below
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: FAILED_WORDS })
      .getByTitle(/^estimate:/),
  ).toHaveCount(0);
  await expect(
    planPanel(page).getByRole("note", { name: ESTIMATE }),
  ).toHaveCount(1);
});

const ESTIMATE =
  "estimate: road legs are straight-line guesses, not real roads";

function planPanel(page: Page): Locator {
  return page.getByRole("region", { name: "Plan", exact: true });
}

function mapArea(page: Page): Locator {
  return page.getByRole("region", { name: "Map of the run" });
}

test("A plan on the offline road map is marked as an estimate", async ({
  page,
}, testInfo) => {
  test.setTimeout(420_000);
  await makeRunFour(page, testInfo);
  await page.reload();

  await expect(stateBadge(page)).toContainText("Plan run #4");
  const pill = planPanel(page).getByRole("note", { name: ESTIMATE });
  await expect(pill).toBeVisible();
  await expect(pill).toHaveText(/estimate/);
  await expect(pill).toHaveAttribute("title", ESTIMATE);
  await expect(pill.locator('[aria-hidden="true"]')).toHaveText("\u2248");
  // by the heading: within a short way of the state badge, in the same panel
  const badge = await boxOf(stateBadge(page));
  const pillBox = await boxOf(pill);
  expect(Math.abs(pillBox.y - badge.y)).toBeLessThan(200);

  const chip = mapArea(page).getByRole("note", { name: ESTIMATE });
  await expect(chip).toBeVisible();
  const mapBox = await boxOf(mapArea(page));
  const chipBox = await boxOf(chip);
  expect(chipBox.x - mapBox.x).toBeLessThan(24); // the map's top-left corner
  expect(chipBox.y - mapBox.y).toBeLessThan(24);
  const view = page.viewportSize()!;
  expect(chipBox.y + chipBox.height).toBeLessThanOrEqual(view.height); // in view before any scroll
  expect(chipBox.x + chipBox.width).toBeLessThanOrEqual(view.width);
});

test("A plan on real roads shows no estimate marker", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium",
    "the real-road run is checked on the desktop browser",
  );
  test.setTimeout(600_000);
  await makeRuns(page, testInfo, 6);
  // the planner's own answer for a run, rewritten to a Valhalla run (W4)
  await page.route(/\/api\/plan-runs\/[^/]+$/, async (route) => {
    const response = await route.fetch();
    const detail = (await response.json()) as Record<string, unknown>;
    await route.fulfill({ response, json: { ...detail, estimate: false } });
  });
  await page.reload();

  await expect(stateBadge(page)).toContainText("Plan run #6");
  await expect(
    page.getByRole("link", { name: "Export GPX of plan run #6" }),
  ).toBeVisible();
  await expect(page.getByRole("note", { name: ESTIMATE })).toHaveCount(0);
  await expect(page.getByTitle(/^estimate:/)).toHaveCount(0);
  await expect(mapArea(page).getByText("estimate")).toHaveCount(0);
});

test("A stale estimate shows both labels", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium",
    "the stale estimate is checked on the desktop browser",
  );
  test.setTimeout(420_000);
  await makeRunFour(page, testInfo);
  await page.getByLabel("Place name").fill("Lago del Moncenisio");
  await page.getByLabel("Latitude").fill("45.2480");
  await page.getByLabel("Longitude").fill("6.9980");
  await page.getByRole("button", { name: "Add place" }).click();
  await expect(
    page.getByRole("list", { name: "Items" }).getByRole("listitem"),
  ).toHaveCount(3);
  await page.reload();

  await expectState(page, "Stale");
  await expect(page.getByText("Plan run #4", { exact: true })).toBeVisible();
  await expect(
    planPanel(page).getByRole("note", { name: ESTIMATE }),
  ).toBeVisible();
  await expect(
    mapArea(page).getByRole("note", { name: ESTIMATE }),
  ).toBeVisible();
});

test("A project with no plan yet says so and points to Calculate", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await makeAnEmptyProject(page, testInfo);
  await expect(stateBadge(page)).toContainText("No plan yet");
  await expect(
    page.getByText("Press Calculate to plan this trip."),
  ).toBeVisible();
  await expect(
    page.getByText("The map shows the plan once one is computed."),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Export GPX" })).toHaveCount(0);
});

// ===================== US-22 The home page tells when a plan broke a hard rule =====================

// The Diagnostics answer with the K2 count rewritten (W4): the packaged planner cannot break a hard rule (W1).
async function diagnosticsCounting(page: Page, count: number): Promise<void> {
  await page.route(/\/api\/diagnostics$/, async (route) => {
    const real = await (await route.fetch()).json();
    real.k2.invariant_violations.all_time = count;
    await route.fulfill({ json: real });
  });
}

const banner = (page: Page): Locator =>
  page
    .getByRole("alert")
    .filter({ hasText: "broke one of the planner's rules" });

async function openHome(page: Page): Promise<void> {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { level: 1, name: "Projects" }),
  ).toBeVisible();
}

test("A rule-breaking plan run raises a banner on the home page", async ({
  page,
}) => {
  await diagnosticsCounting(page, 1);
  await openHome(page);
  await expect(banner(page)).toContainText("1");
  await expect(
    banner(page).getByRole("link", { name: "Diagnostics" }),
  ).toHaveAttribute("href", "#/diagnostics");
});

test("An acknowledged banner stays away in this browser", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "one width is enough");
  await diagnosticsCounting(page, 1);
  await openHome(page);
  await banner(page).getByRole("button", { name: "Acknowledge" }).click();
  await expect(banner(page)).toHaveCount(0);
  await openHome(page);
  await page.reload();
  await expect(
    page.getByRole("heading", { level: 1, name: "Projects" }),
  ).toBeVisible();
  await expect(banner(page)).toHaveCount(0);
});

test("The banner comes back when the count grows", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "one width is enough");
  await diagnosticsCounting(page, 1);
  await openHome(page);
  await banner(page).getByRole("button", { name: "Acknowledge" }).click();
  await expect(banner(page)).toHaveCount(0);
  await page.unroute(/\/api\/diagnostics$/);
  await diagnosticsCounting(page, 2);
  await page.reload();
  await expect(banner(page)).toContainText("2");
});

test("Another browser still sees the banner", async ({
  browser,
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "two contexts of its own");
  const baseURL = testInfo.project.use.baseURL ?? "http://127.0.0.1:8080";
  await diagnosticsCounting(page, 1);
  await openHome(page);
  await banner(page).getByRole("button", { name: "Acknowledge" }).click();
  await expect(banner(page)).toHaveCount(0);
  const giulia = await browser.newContext({ ...devices["iPhone 14"], baseURL });
  try {
    const phone = await giulia.newPage();
    await diagnosticsCounting(phone, 1);
    await openHome(phone);
    await expect(banner(phone)).toContainText("1");
  } finally {
    await giulia.close();
  }
});

test("No banner when no plan run broke a rule", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "one width is enough");
  await openHome(page);
  await expect(
    page.getByText("No projects yet.").or(page.getByRole("list")),
  ).toBeVisible();
  await expect(banner(page)).toHaveCount(0);
});

test("The home page still works when the count cannot be read", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "one width is enough");
  const name = `Alpi Occidentali giugno 2027 (${testInfo.project.name} ${Date.now()})`;
  await page.goto("/");
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "New project" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await page.route(/\/api\/diagnostics$/, (route) =>
    route.fulfill({
      status: 503,
      json: { code: "unavailable", message: "Diagnostics are unavailable" },
    }),
  );
  await openHome(page);
  await expect(page.getByRole("link", { name })).toBeVisible();
  await expect(banner(page)).toHaveCount(0);
});

test("The banner still shows when the browser refuses to keep the acknowledgement", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "one width is enough");
  const name = `Alpi Occidentali giugno 2027 (${testInfo.project.name} ${Date.now()})`;
  await page.goto("/");
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "New project" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await page.addInitScript(() => {
    const refuse = (): never => {
      throw new DOMException("refused", "SecurityError");
    };
    Storage.prototype.getItem = refuse;
    Storage.prototype.setItem = refuse;
  });
  await diagnosticsCounting(page, 1);
  await openHome(page);
  await banner(page).getByRole("button", { name: "Acknowledge" }).click();
  await openHome(page);
  await page.reload();
  await expect(banner(page)).toContainText("1");
  await expect(page.getByRole("link", { name })).toBeVisible();
});

// The map has drawn the run's lines (asked of MapLibre through the `?e2e=1` hook, as run-map.spec.ts does).
async function expectLinesDrawn(page: Page): Promise<void> {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const map = (
            window as unknown as {
              __overlandRunMap?: {
                queryRenderedFeatures(options: { layers: string[] }): unknown[];
              };
            }
          ).__overlandRunMap;
          return map?.queryRenderedFeatures({ layers: ["track"] }).length ?? 0;
        }),
      { message: "the map draws the track line" },
    )
    .toBeGreaterThan(0);
}

// Evidence for the orchestrator, `make e2e-local` only (E2E_START_LOCAL): full-page screenshots of the home page, the
// project page with plan run #4 and the Diagnostics page, saved under .data/e2e/slice-12 (gitignored). Never compared
// by pixels, never uploaded by CI.
test("Screenshots of the three pages are saved for the orchestrator", async ({
  page,
}, testInfo) => {
  test.skip(
    !process.env.E2E_START_LOCAL,
    "evidence is taken under make e2e-local only",
  );
  test.setTimeout(420_000);
  if (testInfo.project.name === "chromium")
    await page.setViewportSize({ width: 1440, height: 900 });
  const folder = path.resolve(
    testInfo.project.testDir,
    "../../.data/e2e/slice-12",
  );

  const projectUrl = await makeRunFour(page, testInfo);
  for (const [where, address] of [
    ["home", "/"],
    ["project", projectUrl.replace("/#/", "/?e2e=1#/")],
    ["diagnostics", "/#/diagnostics"],
  ] as const) {
    await page.goto(address);
    if (where === "project") {
      await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible({
        timeout: 30_000,
      });
      await expectLinesDrawn(page);
    } else if (where === "diagnostics")
      await expect(
        page.getByRole("heading", { name: "K2 invariant violations" }),
      ).toBeVisible();
    else await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.screenshot({
      path: path.join(folder, `${where}-${testInfo.project.name}.png`),
      fullPage: true,
    });
  }
});

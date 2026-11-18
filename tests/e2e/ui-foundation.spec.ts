// Slice 12 UI foundation (US-20, US-21, US-22): the @ui scenarios of
// tests/acceptance/overland_route_planner_mvp/slice-12-ui-foundation.feature, one test per scenario (one per row of
// the plan-state outline), named after it. DISTILL skeleton: every test was `test.fixme` (skipped, CI stays green);
// DELIVER writes each body and turns it into `test` in the step that makes the scenario pass.
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
  expect,
  test,
  type Locator,
  type Page,
  type TestInfo,
} from "@playwright/test";
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

test.fixme("The map stays readable on a phone at trip-wide zoom", async () => {});

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
  await expect(page.getByRole("link", { name: "Export GPX" })).toHaveCount(0);
  await expect(page.getByText(/^\W*estimate\W*$/i)).toHaveCount(0);
  await expect(page.getByTitle(/^estimate:/)).toHaveCount(0);
});

test.fixme("A plan on the offline road map is marked as an estimate", async () => {});

test.fixme("A plan on real roads shows no estimate marker", async () => {});

test.fixme("A stale estimate shows both labels", async () => {});

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

test.fixme("A rule-breaking plan run raises a banner on the home page", async () => {});

test.fixme("An acknowledged banner stays away in this browser", async () => {});

test.fixme("The banner comes back when the count grows", async () => {});

test.fixme("Another browser still sees the banner", async () => {});

test.fixme("No banner when no plan run broke a rule", async () => {});

test.fixme("The home page still works when the count cannot be read", async () => {});

test.fixme("The banner still shows when the browser refuses to keep the acknowledgement", async () => {});

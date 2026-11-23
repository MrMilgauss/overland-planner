// Evidence for the orchestrator (slice 12b, DoD 5), `make e2e-local` only (E2E_START_LOCAL): full-page screenshots of
// Build the trip, Planning and Your route at 1440 and 768 px (chromium) and 390 px (webkit-iphone14), light and dark,
// on the light base map and on Terrain, saved under .data/e2e/slice-12b/ (gitignored). Unlike every other test this one
// lets the real base map and Terrain tiles load. Never compared, never uploaded by CI.
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

type DrawnMap = {
  loaded(): boolean;
  isMoving(): boolean;
  once(e: string, f: () => void): void;
};

// The map has finished drawing: its own 'idle' event (or already idle), never a fixed sleep.
async function drawn(page: Page): Promise<void> {
  await page.waitForFunction(
    () =>
      !!(window as unknown as { __overlandRunMap?: unknown }).__overlandRunMap,
  );
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const map = (window as unknown as { __overlandRunMap: DrawnMap })
          .__overlandRunMap;
        if (map.loaded() && !map.isMoving()) resolve();
        else map.once("idle", () => resolve());
      }),
  );
}

async function terrain(page: Page, on: boolean): Promise<void> {
  const button = page.getByRole("button", { name: "Terrain" });
  if ((await button.getAttribute("aria-pressed")) !== String(on))
    await button.click();
  await expect(button).toHaveAttribute("aria-pressed", String(on));
}

const saved: string[] = [];

async function shootAll(
  page: Page,
  testInfo: TestInfo,
  phase: string,
  width: number,
): Promise<void> {
  const folder = path.resolve(
    testInfo.project.testDir,
    "../../.data/e2e/slice-12b",
  );
  mkdirSync(folder, { recursive: true });
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const base of ["light-map", "terrain"]) {
      await terrain(page, base === "terrain");
      await drawn(page);
      const file = path.join(
        folder,
        `${phase}-${width}px-${scheme}-${base}.png`,
      );
      await page.screenshot({ path: file, fullPage: true });
      saved.push(file);
    }
  }
}

const WIDTHS: [string, number][] = [
  ["chromium", 1440],
  ["chromium", 768],
  ["webkit-iphone14", 390],
];

for (const [project, width] of WIDTHS) {
  test(`Screenshots of the three phases at ${width} px`, async ({
    page,
  }, testInfo) => {
    test.skip(
      !process.env.E2E_START_LOCAL,
      "local evidence only (make e2e-local)",
    );
    test.skip(testInfo.project.name !== project, `${project} only`);
    test.setTimeout(480_000);
    if (project === "chromium")
      await page.setViewportSize({ width, height: 900 });

    const planUrl = await planARun(page, testInfo);
    await page.goto(planUrl.replace("/#/", "/?e2e=1#/"));
    await expect(page.getByRole("link", { name: "Export GPX" })).toBeVisible({
      timeout: 60_000,
    });
    await shootAll(page, testInfo, "your-route", width);

    await page.getByRole("button", { name: "Edit trip" }).click();
    await expect(
      page.getByRole("button", { name: "Plan the route" }),
    ).toBeVisible();
    await shootAll(page, testInfo, "build-the-trip", width);

    await holdPlanning(page);
    await page.getByRole("button", { name: "Plan the route" }).click();
    await expect(page.getByRole("region", { name: "Planning" })).toBeVisible();
    await shootAll(page, testInfo, "planning", width);

    console.log(`saved screenshots:\n${saved.join("\n")}`);
  });
}

// A real run on the offline road map (Assietta trail, Torino as Start and End); the address of its project page.
async function planARun(page: Page, testInfo: TestInfo): Promise<string> {
  const name = `Screenshots (${testInfo.project.name} ${Date.now()})`;
  const id = (
    (await (
      await page.request.post("/api/projects", { data: { name } })
    ).json()) as { id: string }
  ).id;
  await page.request.post(`/api/projects/${id}/tracks`, {
    multipart: {
      files: {
        name: "assietta.gpx",
        mimeType: "application/gpx+xml",
        buffer: readFileSync(
          path.join(
            testInfo.project.testDir,
            "../acceptance/overland_route_planner_mvp/fixtures/gpx/assietta.gpx",
          ),
        ),
      },
    },
  });
  const home = (await (
    await page.request.post(`/api/projects/${id}/pois`, {
      data: { name: "Casa Marco, Torino", lat: 45.0703, lon: 7.6869 },
    })
  ).json()) as { id: string };
  await page.request.put(`/api/projects/${id}/anchors`, {
    data: { start_item_id: home.id, end_item_id: home.id },
  });
  await page.request.post(`/api/projects/${id}/plan-runs`);
  await expect
    .poll(
      async () =>
        (
          (await (
            await page.request.get(`/api/projects/${id}/plan-runs`)
          ).json()) as { status: string }[]
        ).filter((run) => run.status === "ready").length,
      { timeout: 120_000, message: "the planner's run is ready" },
    )
    .toBe(1);
  return `/#/projects/${id}`;
}

// Planning without a real solve: the answer to "Plan the route" and to the job, held at "solving".
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

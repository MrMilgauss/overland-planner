// Phone journey of slice 02: "Giulia reads the itinerary on her phone". SSOT: the @ui @phone scenario in
// tests/acceptance/overland_route_planner_mvp/slice-02-directional-optimizer.feature. Its step definitions
// (steps/browser.py, PhoneItineraryJourney) prepare plan run #4 on a real planner, run this spec at a 390 px wide
// viewport (no real device) and assert on what it reports. Without their settings it is skipped, so CI job 7 and
// `make e2e-local` do not run it. The spec only records what the screen shows; the verdict is the Python Then's.
import { writeFile } from "node:fs/promises";
import path from "node:path";
import { expect, test } from "@playwright/test";

const projectId = process.env.PHONE_PROJECT_ID;
const resultDir = process.env.PHONE_RESULT_DIR;
const screenWidth = Number(process.env.PHONE_SCREEN_WIDTH ?? "390");

test.use({
  viewport: { width: screenWidth, height: 844 },
  isMobile: true,
  hasTouch: true,
});

test("Giulia opens the results on her phone", async ({ page }) => {
  test.skip(
    !projectId || !resultDir,
    "driven by the acceptance step of slice 02",
  );
  test.setTimeout(120_000);

  await page.goto(`/#/projects/${projectId}`);
  const itinerary = page.getByRole("list", { name: "Itinerary" });
  await expect(itinerary).toBeVisible({ timeout: 30_000 });

  const rows = [];
  for (const row of await itinerary.getByRole("listitem").all()) {
    const box = await row.boundingBox();
    rows.push({
      text: await row.innerText(),
      left: box?.x ?? null,
      right: box ? box.x + box.width : null,
      visible: await row.isVisible(),
    });
  }
  // The totals are the summary card's numbers, no longer a part of the itinerary (D286).
  const totals = page
    .getByRole("region", { name: "Your route", exact: true })
    .getByLabel("Totals");
  const totalsText =
    (await totals.count()) > 0 ? await totals.first().innerText() : null;

  const headerLine = page.locator(".provider");
  const headerText =
    (await headerLine.count()) > 0
      ? await headerLine.first().innerText()
      : null;
  // The objective is not a control on Your route: its label (the run's objective_label) is a line inside the closed
  // Details (D285), opened here so that the widest engine lines are on screen too when the width is measured below.
  await page
    .getByRole("region", { name: "Your route", exact: true })
    .getByText("Details", { exact: true })
    .click();
  await expect(
    page
      .getByRole("region", { name: "Your route", exact: true })
      .locator(".objective"),
  ).toBeVisible();
  const pageWidth = await page.evaluate(() =>
    Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
  );
  expect(
    pageWidth,
    "no horizontal scroll with the header line and the objective line",
  ).toBeLessThanOrEqual(screenWidth);
  if (headerText !== null) await expect(headerLine.first()).toBeVisible();

  await writeFile(
    path.join(resultDir!, "result.json"),
    JSON.stringify({
      screen_width: screenWidth,
      page_width: pageWidth,
      rows,
      totals_text: totalsText,
      header_text: headerText,
    }),
  );
});

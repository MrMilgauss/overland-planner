// Browser journey of slice 01a (step 03-10, CI job 7 on chromium and webkit-iphone14 against the compose stack).
// NON-SSOT UI regression check: every slice-01a scenario drives the HTTP API; this one has Marco in a browser.
// Single example by design (E2E level): the trail is the synthetic assietta.gpx of the acceptance fixtures.
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const ASSIETTA =
  "../acceptance/overland_route_planner_mvp/fixtures/gpx/assietta.gpx";

function itemRow(page: Page, name: string) {
  return page
    .getByRole("list", { name: "Your trip" })
    .getByRole("listitem")
    .filter({ hasText: name });
}

async function addPlace(
  page: Page,
  name: string,
  lat: string,
  lon: string,
): Promise<void> {
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("button", { name: "Type coordinates" }).click();
  const form = page.getByRole("form", { name: "Type coordinates" });
  await form.getByLabel("Name").fill(name);
  await form.getByLabel("Latitude").fill(lat);
  await form.getByLabel("Longitude").fill(lon);
  await form.getByRole("button", { name: "Add" }).click();
}

async function setFromTheRow(
  page: Page,
  place: string,
  choice: string,
): Promise<void> {
  await itemRow(page, place)
    .getByRole("button", { name: `Actions for ${place}` })
    .click();
  await page.getByRole("button", { name: choice }).click();
}

test("Marco creates a project, imports a trail, adds a POI and sets Start and End in the browser", async ({
  page,
}, testInfo) => {
  // Both browser projects run at once against the same planner: each creates its own project.
  const projectName = `Alpi Occidentali giugno 2027 (${testInfo.project.name} ${Date.now()})`;

  await page.goto("/");
  await page.getByLabel("Project name").fill(projectName);
  await page.getByRole("button", { name: "New project" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: projectName }),
  ).toBeVisible();

  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("button", { name: "Upload GPX trails" }).click();
  await (await chooser).setFiles(path.join(testInfo.project.testDir, ASSIETTA));
  await expect(itemRow(page, "Strada dell'Assietta")).toContainText("Trail");

  await addPlace(page, "Briancon", "144.8990", "6.6430");
  await expect(page.getByRole("alert")).toHaveText(
    "Latitude must be between -90 and 90",
  );
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(itemRow(page, "Briancon")).toHaveCount(0);

  await addPlace(page, "Casa Marco, Torino", "45.0703", "7.6869");
  await expect(itemRow(page, "Casa Marco, Torino")).toContainText("Place");

  await setFromTheRow(page, "Casa Marco, Torino", "Set as start");
  await setFromTheRow(page, "Casa Marco, Torino", "Set as end");
  await expect(
    itemRow(page, "Casa Marco, Torino").getByText("Start", { exact: true }),
  ).toBeVisible();
  await expect(
    itemRow(page, "Casa Marco, Torino").getByText("End", { exact: true }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Projects" }).click();
  await expect(page.getByRole("link", { name: projectName })).toBeVisible();
  await page.getByRole("link", { name: projectName }).click();
  await expect(
    itemRow(page, "Casa Marco, Torino").getByText("End", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Your trip" }).getByRole("listitem"),
  ).toHaveCount(2);
});

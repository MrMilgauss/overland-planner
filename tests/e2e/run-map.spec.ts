// The run map of slice 09 (step 10-04), in Chromium on a desktop and on the iPhone 14 profile. Two uses:
//  - on its own (`make e2e-local`, CI job 7): Marco makes a small plan in the browser and checks its map;
//  - driven by the @ui @phone scenario "Giulia uses the map on her phone" (steps/browser.py, MapPhoneJourney): the
//    plan run exists, the spec opens its project at 390 px and writes what the screen showed to result.json.
// Tiles never come from the internet: every request to a host other than the planner's is answered with a blank tile.
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { serveBlankTiles } from './blankTile';

const ASSIETTA = '../acceptance/overland_route_planner_mvp/fixtures/gpx/assietta.gpx';
const HOME = 'Casa Marco, Torino';
const projectId = process.env.MAP_PROJECT_ID;
const resultDir = process.env.MAP_RESULT_DIR;
const driven = Boolean(projectId && resultDir);
const screenWidth = Number(process.env.MAP_SCREEN_WIDTH ?? '0');

if (driven && screenWidth > 0) {
  test.use({ viewport: { width: screenWidth, height: 844 }, isMobile: true, hasTouch: true });
}

async function makeAPlan(page: Page, testDir: string, projectName: string): Promise<void> {
  await page.goto('/');
  await page.getByLabel('Project name').fill(projectName);
  await page.getByRole('button', { name: 'New project' }).click();
  await expect(page.getByRole('heading', { level: 1, name: projectName })).toBeVisible();
  await page.getByLabel('GPX files').setInputFiles(path.join(testDir, ASSIETTA));
  await page.getByRole('button', { name: 'Import' }).click();
  await expect(page.getByRole('list', { name: 'Items' }).getByRole('listitem')).toHaveCount(1);
  await page.getByLabel('Place name').fill(HOME);
  await page.getByLabel('Latitude').fill('45.0703');
  await page.getByLabel('Longitude').fill('7.6869');
  await page.getByRole('button', { name: 'Add place' }).click();
  await expect(page.getByRole('list', { name: 'Items' }).getByRole('listitem')).toHaveCount(2);
  await page.getByLabel('Start', { exact: true }).selectOption({ label: HOME });
  await page.getByLabel('End', { exact: true }).selectOption({ label: HOME });
  await page.getByRole('button', { name: 'Set Start and End' }).click();
  await page.getByRole('button', { name: 'Calculate' }).click();
  await expect(page.getByRole('link', { name: 'Export GPX' })).toBeVisible({ timeout: 120_000 });
}

async function centres(markers: Locator): Promise<{ x: number; y: number }[]> {
  const found = [];
  for (const marker of await markers.all()) {
    const box = await marker.boundingBox();
    if (box) found.push({ x: box.x + box.width / 2, y: box.y + box.height / 2 });
  }
  return found;
}

const spread = (points: { x: number; y: number }[]): number =>
  Math.hypot(points[0].x - points.at(-1)!.x, points[0].y - points.at(-1)!.y);

test('the map of the run shows its roads, tracks, numbers and credit, and pans and zooms', async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await serveBlankTiles(page, String(testInfo.project.use.baseURL));

  if (driven) await page.goto(`/#/projects/${projectId}`);
  else await makeAPlan(page, testInfo.project.testDir, `Mappa ${testInfo.project.name} ${Date.now()}`);

  const map = page.getByRole('region', { name: 'Map of the run' });
  await expect(map.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 60_000 });
  const config = await (await page.request.get('/api/config/map')).json();
  const credit = map.locator('.maplibregl-ctrl-attrib');
  await expect(credit).toBeVisible();
  await expect(credit).toContainText(String(config.attribution).split('|')[0].trim().slice(0, 20));
  await expect(map.getByRole('button', { name: /attribution/i })).toHaveCount(0); // always open: nothing to close

  const numbered = map.locator('.run-marker.numbered');
  await expect(numbered.first()).toBeVisible();
  const numbers = await numbered.allInnerTexts();
  expect(numbers.length).toBeGreaterThan(1);
  for (const text of numbers) expect(text).toMatch(/\d/);

  const screen = page.viewportSize()!.width;
  const pageWidth = await page.evaluate(() =>
    Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
  );
  expect(pageWidth, 'no horizontal scroll').toBeLessThanOrEqual(screen);

  await map.scrollIntoViewIfNeeded();
  const frame = (await map.locator('canvas.maplibregl-canvas').boundingBox())!;
  const middle = { x: frame.x + frame.width / 2, y: frame.y + frame.height / 2 };

  const before = await centres(numbered);
  await page.mouse.move(middle.x, middle.y);
  await page.mouse.down();
  await page.mouse.move(middle.x - 60, middle.y - 40, { steps: 8 });
  await page.mouse.up();
  await expect
    .poll(async () => (await centres(numbered))[0].x, { message: 'the map pans' })
    .not.toBeCloseTo(before[0].x, 0);
  const panned = await centres(numbered);
  const widthBefore = spread(panned);

  // A wheel on a desktop; on a phone profile the map's own Zoom in control (Playwright has no pinch, and mobile WebKit
  // has no wheel).
  if (testInfo.project.use.isMobile || driven) await map.getByRole('button', { name: 'Zoom in' }).click();
  else {
    await page.mouse.move(middle.x, middle.y);
    await page.mouse.wheel(0, -400);
  }
  await expect
    .poll(async () => spread(await centres(numbered)), { message: 'the map zooms' })
    .toBeGreaterThan(widthBefore);

  if (driven) {
    await writeFile(
      path.join(resultDir!, 'result.json'),
      JSON.stringify({
        screen_width: screen,
        page_width: pageWidth,
        canvas_visible: true,
        credit_text: await credit.innerText(),
        numbers,
        panned: true,
        zoomed: true,
      }),
    );
  }
});

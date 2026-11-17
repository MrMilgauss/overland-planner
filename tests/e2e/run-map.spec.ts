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
// Step 10-05 (POI by map click): the one action a driven run does; empty = the spec makes its own plan and does them all.
const poiAction = process.env.MAP_POI_ACTION ?? '';
const SUSA = {
  lat: Number(process.env.MAP_POI_LAT ?? '45.1376'),
  lon: Number(process.env.MAP_POI_LON ?? '7.0486'),
};

if (driven && screenWidth > 0) {
  test.use({
    viewport: { width: screenWidth, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
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
  await expect(page.getByRole('link', { name: 'Export GPX' })).toBeVisible({
    timeout: 120_000,
  });
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
  test.skip(poiAction !== '', 'a POI run is driven: the map checks are not');
  test.setTimeout(180_000);
  await serveBlankTiles(page, String(testInfo.project.use.baseURL));

  if (driven) await page.goto(`/#/projects/${projectId}`);
  else
    await makeAPlan(page, testInfo.project.testDir, `Mappa ${testInfo.project.name} ${Date.now()}`);

  const map = page.getByRole('region', { name: 'Map of the run' });
  await expect(map.locator('canvas.maplibregl-canvas')).toBeVisible({
    timeout: 60_000,
  });
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
  const middle = {
    x: frame.x + frame.width / 2,
    y: frame.y + frame.height / 2,
  };

  const before = await centres(numbered);
  await page.mouse.move(middle.x, middle.y);
  await page.mouse.down();
  await page.mouse.move(middle.x - 60, middle.y - 40, { steps: 8 });
  await page.mouse.up();
  await expect
    .poll(async () => (await centres(numbered))[0].x, {
      message: 'the map pans',
    })
    .not.toBeCloseTo(before[0].x, 0);
  const panned = await centres(numbered);
  const widthBefore = spread(panned);

  // A wheel on a desktop; on a phone profile the map's own Zoom in control (Playwright has no pinch, and mobile WebKit
  // has no wheel).
  if (testInfo.project.use.isMobile || driven)
    await map.getByRole('button', { name: 'Zoom in' }).click();
  else {
    await page.mouse.move(middle.x, middle.y);
    await page.mouse.wheel(0, -400);
  }
  await expect
    .poll(async () => spread(await centres(numbered)), {
      message: 'the map zooms',
    })
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

// ---------------------------------------------------------------------------------- POI by map click (step 10-05)
// The map's own centre and zoom are on its frame (data-center "lng,lat", data-zoom): the spec turns a place into the
// pixel to click with the Web Mercator of MapLibre (a 512 px world at zoom 0), and zooms in about that pixel first, so
// that a pixel is a few metres and the POI lands where Marco clicked.
const WORLD = 512;
const CLOSE_ENOUGH_ZOOM = 13;

async function viewOf(frame: Locator): Promise<{ lng: number; lat: number; zoom: number }> {
  return frame.evaluate((element) => {
    const [lng, lat] = (element as HTMLElement).dataset.center!.split(',').map(Number);
    return { lng, lat, zoom: Number((element as HTMLElement).dataset.zoom) };
  });
}

async function settled(
  page: Page,
  frame: Locator,
): Promise<{ lng: number; lat: number; zoom: number }> {
  await expect
    .poll(
      async () => {
        const before = JSON.stringify(await viewOf(frame));
        await page.waitForTimeout(250); // sampling interval of the poll, not a wait for a result
        return before === JSON.stringify(await viewOf(frame));
      },
      { message: 'the map stands still' },
    )
    .toBe(true);
  return viewOf(frame);
}

const mercator = (lat: number, lon: number, zoom: number): { x: number; y: number } => {
  const size = WORLD * 2 ** zoom;
  const sine = Math.sin((lat * Math.PI) / 180);
  return {
    x: ((lon + 180) / 360) * size,
    y: (0.5 - Math.log((1 + sine) / (1 - sine)) / (4 * Math.PI)) * size,
  };
};

async function pixelOf(page: Page, frame: Locator, lat: number, lon: number) {
  const view = await settled(page, frame);
  const centre = mercator(view.lat, view.lng, view.zoom);
  const target = mercator(lat, lon, view.zoom);
  const box = (await frame.locator('canvas.maplibregl-canvas').boundingBox())!;
  return {
    x: box.x + box.width / 2 + target.x - centre.x,
    y: box.y + box.height / 2 + target.y - centre.y,
    box,
    zoom: view.zoom,
  };
}

async function zoomInAbout(page: Page, frame: Locator, lat: number, lon: number): Promise<void> {
  if (test.info().project.use.isMobile) return; // mobile WebKit has no wheel: a pixel is wider there
  for (let tries = 0; tries < 20; tries += 1) {
    const spot = await pixelOf(page, frame, lat, lon);
    if (spot.zoom >= CLOSE_ENOUGH_ZOOM) return;
    expect(spot.x, 'the place is in view').toBeGreaterThan(spot.box.x);
    expect(spot.x, 'the place is in view').toBeLessThan(spot.box.x + spot.box.width);
    expect(spot.y, 'the place is in view').toBeGreaterThan(spot.box.y);
    expect(spot.y, 'the place is in view').toBeLessThan(spot.box.y + spot.box.height);
    await page.mouse.move(spot.x, spot.y);
    await page.mouse.wheel(0, -500);
  }
  throw new Error('the map did not zoom in');
}

const nameForm = (page: Page): Locator => page.getByRole('form', { name: 'Add a place here' });

async function clickModeOn(map: Locator): Promise<string> {
  const toggle = map.getByRole('button', { name: 'Click on map' });
  await expect(toggle, 'the map has a Click on map control').toBeVisible({
    timeout: 15_000,
  });
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  return (await toggle.getAttribute('aria-pressed')) ?? '';
}

async function clickPlace(page: Page, map: Locator, lat: number, lon: number): Promise<number> {
  const frame = map.locator('.map');
  await zoomInAbout(page, frame, lat, lon);
  const spot = await pixelOf(page, frame, lat, lon);
  await page.mouse.click(spot.x, spot.y);
  await expect(nameForm(page)).toBeVisible();
  return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / 2 ** (spot.zoom + 1); // metres a pixel stands for
}

async function nameIt(page: Page, name: string): Promise<void> {
  await nameForm(page).getByLabel('Name').fill(name);
  await nameForm(page).getByRole('button', { name: 'Add' }).click();
}

async function clickEntryMarker(page: Page, map: Locator): Promise<void> {
  const box = (await map.locator('.run-marker.entry').first().boundingBox())!;
  // Five pixels off the middle of the marker: the click is "next to" the entry, which is what snapping is for.
  await page.mouse.click(box.x + box.width / 2 + 5, box.y + box.height / 2);
  await expect(nameForm(page)).toBeVisible();
}

test('a POI by a click on the map: named, placed, snapped to an entry, cancelled', async ({
  page,
}, testInfo) => {
  test.skip(driven && poiAction === '', 'driven by another scenario');
  test.setTimeout(150_000);
  await serveBlankTiles(page, String(testInfo.project.use.baseURL));
  if (driven) await page.goto(`/#/projects/${projectId}`);
  else
    await makeAPlan(page, testInfo.project.testDir, `POI ${testInfo.project.name} ${Date.now()}`);

  const map = page.getByRole('region', { name: 'Map of the run' });
  await expect(map.locator('canvas.maplibregl-canvas')).toBeVisible({
    timeout: 60_000,
  });
  await expect(map.locator('.run-marker.entry').first()).toBeVisible();
  const items = page.getByRole('list', { name: 'Items' });
  const mode = await clickModeOn(map);
  const action = (name: string): boolean => poiAction === '' || poiAction === name;
  const seen = {
    form_shown: false,
    form_gone: false,
    listed: false,
    mode_seen: mode,
    metres_per_pixel: 0,
  };

  if (action('entry')) {
    const name = process.env.MAP_POI_NAME || 'Assietta trailhead';
    await clickEntryMarker(page, map);
    seen.form_shown = true;
    await nameIt(page, name);
    await expect(items.getByText(name)).toBeVisible();
    seen.form_gone = true;
    seen.listed = true;

    const id = driven ? projectId : new URL(page.url()).hash.split('/').pop();
    const listed = await (await page.request.get(`/api/projects/${id}/items`)).json();
    const poi = listed.find((item: { name: string }) => item.name === name);
    const track = listed.find((item: { type: string }) => item.type === 'track');
    expect(poi.location, 'the POI is at the entry, exactly').toEqual(track.entry);
  }

  if (action('click')) {
    const name = process.env.MAP_POI_NAME || 'Susa trailhead';
    seen.metres_per_pixel = await clickPlace(page, map, SUSA.lat, SUSA.lon);
    seen.form_shown = true;
    const form = (await nameForm(page).boundingBox())!;
    expect(form.x + form.width, 'the form fits the screen').toBeLessThanOrEqual(
      page.viewportSize()!.width,
    );
    await nameIt(page, name);
    await expect(nameForm(page)).toHaveCount(0);
    await expect(items.getByText(name)).toBeVisible();
    seen.form_gone = true;
    seen.listed = true;
  }

  if (action('cancel')) {
    await clickPlace(page, map, SUSA.lat, SUSA.lon);
    seen.form_shown = true;
    const count = await items.getByRole('listitem').count();
    await nameForm(page).getByRole('button', { name: 'Cancel' }).click();
    await expect(nameForm(page)).toHaveCount(0);
    seen.form_gone = true;
    if (poiAction === '') {
      await clickPlace(page, map, SUSA.lat, SUSA.lon); // Escape closes it too
      await page.keyboard.press('Escape');
      await expect(nameForm(page)).toHaveCount(0);
      await clickPlace(page, map, SUSA.lat, SUSA.lon); // an empty name keeps it open with the planner's message
      await nameForm(page).getByRole('button', { name: 'Add' }).click();
      await expect(nameForm(page).getByRole('alert')).toBeVisible();
      await nameForm(page).getByRole('button', { name: 'Cancel' }).click();
    }
    await expect(items.getByRole('listitem')).toHaveCount(count);
  }

  if (driven) {
    await writeFile(path.join(resultDir!, 'result.json'), JSON.stringify(seen));
  }
});

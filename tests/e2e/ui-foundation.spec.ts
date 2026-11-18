// Slice 12 UI foundation (US-20, US-21, US-22): the @ui scenarios of
// tests/acceptance/overland_route_planner_mvp/slice-12-ui-foundation.feature, one test per scenario (one per row of
// the plan-state outline), named after it. DISTILL skeleton: every test is `test.fixme` (skipped, CI stays green);
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
import path from 'node:path';
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { serveBlankTiles } from './blankTile';
import { contrastRatio, parseColour, readColours } from './contrast';

const ASSIETTA = '../acceptance/overland_route_planner_mvp/fixtures/gpx/assietta.gpx';
const HOME = 'Casa Marco, Torino';

// Marco's project, planned: his own project (both browser projects run at once), the Assietta trail, a start and end,
// and a plan on the offline road map. Returns the project's address.
async function makeAPlannedProject(page: Page, testInfo: TestInfo): Promise<string> {
  await serveBlankTiles(page, testInfo.project.use.baseURL ?? 'http://127.0.0.1:8080');
  const name = `Alpi Occidentali giugno 2027 (${testInfo.project.name} ${Date.now()})`;
  await page.goto('/');
  await page.getByLabel('Project name').fill(name);
  await page.getByRole('button', { name: 'New project' }).click();
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible();
  await page.getByLabel('GPX files').setInputFiles(path.join(testInfo.project.testDir, ASSIETTA));
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
  return page.url();
}

// ===================== US-20 One product: map first, one look, on any screen =====================

test.fixme('On a laptop the map is the main surface', async () => {});

test.fixme('On a phone nothing scrolls sideways and every target is touch-sized', async () => {});

test.fixme('At tablet width nothing overlaps', async () => {});

test.fixme('Every page uses the same look and the controls are grouped by task', async () => {});

test('The theme follows the system and text stays readable outdoors', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'one browser is enough for the colours');
  test.setTimeout(180_000);

  // The helper itself, against known pairs: black on white, and two pairs of the D265 table.
  expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 1);
  expect(contrastRatio('#1d4ed8', '#ffffff')).toBeCloseTo(6.7, 1);
  expect(contrastRatio('#e6e8eb', '#121417')).toBeCloseTo(15.0, 1);

  const projectUrl = await makeAPlannedProject(page, testInfo);
  await page.goto(projectUrl);
  await expect(page.getByRole('link', { name: 'Export GPX' })).toBeVisible({ timeout: 30_000 });

  for (const scheme of ['dark', 'light'] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    const token = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue('--color-bg').trim(),
    );
    expect(token, `--color-bg is defined in the ${scheme} look`).toMatch(/^#[0-9a-f]{3,6}$/i);
    const body = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(parseColour(body), `the ${scheme} page background is the token`).toEqual(parseColour(token));

    const texts = await readColours(page, 'text');
    expect(texts.length).toBeGreaterThan(20);
    const weak = texts
      .map((t) => ({ ...t, ratio: contrastRatio(t.colour, t.background) }))
      .filter((t) => t.ratio < 4.5)
      .map((t) => `${t.text.slice(0, 40)} ${t.colour} on ${t.background} = ${t.ratio.toFixed(2)}`);
    expect(weak, `text under 4.5:1 in the ${scheme} look`).toEqual([]);
  }
});

test('Keyboard focus is always visible', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'keyboard focus is checked on the desktop browser');
  test.setTimeout(180_000);

  const projectUrl = await makeAPlannedProject(page, testInfo);
  await page.goto(projectUrl);
  const exportGpx = page.getByRole('link', { name: 'Export GPX' });
  await expect(exportGpx).toBeVisible({ timeout: 30_000 });

  await page.keyboard.press('Tab'); // keyboard use is on; from here focus() shows a focus ring as Tab does
  await page.getByRole('button', { name: 'Calculate' }).focus();
  const seen: string[] = [];
  for (let step = 0; step < 12; step += 1) {
    const look = await readColours(page, 'focus');
    seen.push(look.element);
    expect(look.outlineStyle, `${look.element} has an outline`).not.toBe('none');
    expect(look.outlineWidth, `${look.element} outline width`).toBeGreaterThanOrEqual(2);
    expect(
      contrastRatio(look.outlineColour, look.background),
      `${look.element} outline against the page`,
    ).toBeGreaterThanOrEqual(3);
    if (await exportGpx.evaluate((el) => el === document.activeElement)) break;
    await page.keyboard.press('Tab');
  }
  expect(seen.at(-1)).toContain('Export GPX');
});

test.fixme('The map stays readable on a phone at trip-wide zoom', async () => {});

// ===================== US-21 Plan state and whether its roads are real =====================

for (const label of ['No plan yet', 'Loading', 'Planning', 'Plan run #6', 'Failed', 'Stale']) {
  test.fixme(`Every plan state has its own label and look: ${label}`, async () => {});
}

test.fixme('While planning, Stop is offered', async () => {});

test.fixme("A Failed run shows the label Failed and the planner's own words", async () => {});

test.fixme('A plan on the offline road map is marked as an estimate', async () => {});

test.fixme('A plan on real roads shows no estimate marker', async () => {});

test.fixme('A stale estimate shows both labels', async () => {});

test.fixme('A project with no plan yet says so and points to Calculate', async () => {});

// ===================== US-22 The home page tells when a plan broke a hard rule =====================

test.fixme('A rule-breaking plan run raises a banner on the home page', async () => {});

test.fixme('An acknowledged banner stays away in this browser', async () => {});

test.fixme('The banner comes back when the count grows', async () => {});

test.fixme('Another browser still sees the banner', async () => {});

test.fixme('No banner when no plan run broke a rule', async () => {});

test.fixme('The home page still works when the count cannot be read', async () => {});

test.fixme('The banner still shows when the browser refuses to keep the acknowledgement', async () => {});

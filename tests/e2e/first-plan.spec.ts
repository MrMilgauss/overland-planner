// Browser journey of slice 01b: "Marco plans the Assietta day trip in his browser". SSOT: the @ui scenario in
// tests/acceptance/overland_route_planner_mvp/slice-01b-skeleton-plan-and-gpx.feature. Its step definitions
// (steps/browser.py) prepare the project on a real planner, run this spec and assert on what it reports. Without
// their settings it is skipped, so CI job 7 and `make e2e-local` do not run it.
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import { expect, test } from '@playwright/test';

const projectId = process.env.FIRST_PLAN_PROJECT_ID;
const resultDir = process.env.FIRST_PLAN_RESULT_DIR;

test('Marco presses Calculate and exports the plan', async ({ page }) => {
  test.skip(!projectId || !resultDir, 'driven by the acceptance step of slice 01b');
  test.setTimeout(180_000);

  await page.goto(`/#/projects/${projectId}`);
  await page.getByRole('button', { name: 'Calculate' }).click({ timeout: 15_000 });

  const exportGpx = page
    .getByRole('link', { name: 'Export GPX' })
    .or(page.getByRole('button', { name: 'Export GPX' }));
  await expect(exportGpx).toBeVisible({ timeout: 120_000 });
  const stopRows = await page
    .getByRole('list', { name: 'Itinerary' })
    .getByRole('listitem')
    .allInnerTexts();

  const [download] = await Promise.all([page.waitForEvent('download'), exportGpx.click()]);
  await download.saveAs(path.join(resultDir!, 'downloaded.gpx'));
  await writeFile(
    path.join(resultDir!, 'result.json'),
    JSON.stringify({
      stop_rows: stopRows,
      downloaded_name: download.suggestedFilename(),
    }),
  );
});

// Home-page smoke of the packaged planner (CI job 7, step 01-09): the built page loads in a real browser and shows
// the Projects heading. Runs on chromium and webkit-iphone14 (web/playwright.config.ts) against PLANNER_URL.
import { expect, test } from '@playwright/test';

test('the planner home page shows the Projects heading', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { level: 1, name: 'Projects' })).toBeVisible();
});

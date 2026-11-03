// Playwright home-page check (CI job 7, step 01-09). CI runs it against the packaged planner on PLANNER_URL;
// `make e2e-local` sets E2E_START_LOCAL=1 so Playwright starts `make run-local` itself.
import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.PLANNER_URL ?? 'http://127.0.0.1:8080';

export default defineConfig({
  testDir: '../tests/e2e',
  outputDir: '../.data/e2e/test-results', // gitignored, outside web/ (prettier, eslint)
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['github']] : 'list',
  use: { baseURL, trace: 'retain-on-failure' },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'webkit-iphone14', use: { ...devices['iPhone 14'] } },
    // Weekly only (weekly.yml, step 02-04); CI job 7 and `make e2e-local` select chromium and webkit-iphone14.
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit-desktop', use: { ...devices['Desktop Safari'] } },
  ],
  webServer: process.env.E2E_START_LOCAL
    ? {
        command: 'make -C .. run-local',
        url: `${baseURL}/healthz`,
        reuseExistingServer: true,
        timeout: 120_000,
      }
    : undefined,
});

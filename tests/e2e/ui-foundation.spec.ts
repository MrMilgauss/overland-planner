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
import { test } from '@playwright/test';

// ===================== US-20 One product: map first, one look, on any screen =====================

test.fixme('On a laptop the map is the main surface', async () => {});

test.fixme('On a phone nothing scrolls sideways and every target is touch-sized', async () => {});

test.fixme('At tablet width nothing overlaps', async () => {});

test.fixme('Every page uses the same look and the controls are grouped by task', async () => {});

test.fixme('The theme follows the system and text stays readable outdoors', async () => {});

test.fixme('Keyboard focus is always visible', async () => {});

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

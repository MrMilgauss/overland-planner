"""pytest-bdd binding: scenarios of slices 01b-11. All @pending: their step definitions and RED scaffolds are written
when DELIVER reaches each slice (user decision 2026-11-02). Collected here so the Gherkin is parsed in every run.
"""

from pytest_bdd import scenarios

for _feature in (
    "slice-01b-skeleton-plan-and-gpx.feature",
    "slice-02-directional-optimizer.feature",
    "slice-03-pi-performance.feature",
    "slice-03b-out-and-back-retrace.feature",
    "slice-04-consideration-list.feature",
    "slice-05-incremental-recalculation.feature",
    "slice-06a-valhalla-on-the-pi.feature",
    "slice-06b-compromise-legs.feature",
    "slice-07-real-gpx-import.feature",
    "slice-08-input-data-hygiene.feature",
    "slice-09-directional-map.feature",
    "slice-10-run-diff-history.feature",
    "slice-11-device-ready-gpx.feature",
):
    scenarios(_feature)

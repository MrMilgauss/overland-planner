"""pytest-bdd binding: scenarios of slices 04-11. All @pending: their step definitions and RED scaffolds are written
when DELIVER reaches each slice (user decision 2026-11-02). Collected here so the Gherkin is parsed in every run.
"""

from pytest_bdd import scenario, scenarios

for _feature in (
    "slice-04-consideration-list.feature",
    "slice-05-incremental-recalculation.feature",
    "slice-06b-compromise-legs.feature",
    "slice-07-real-gpx-import.feature",
    "slice-08-input-data-hygiene.feature",
    "slice-10-run-diff-history.feature",
    "slice-11-device-ready-gpx.feature",
):
    scenarios(_feature)


# Slice 09 is enabled in CI (step 10-06); these three wait for slice 08 and carry their own `@pending` (D256).
SLICE_09 = "slice-09-directional-map.feature"


@scenario(SLICE_09, "The map follows a reversed track")
def test_the_map_follows_a_reversed_track() -> None:
    """Waits for slice 08 (D256)."""


@scenario(SLICE_09, "Marco reviews the route with its warnings on the map and exports it")
def test_marco_reviews_the_route_with_its_warnings_on_the_map_and_exports_it() -> None:
    """Waits for slice 08 (D256)."""


@scenario(SLICE_09, "A POI clicked next to an existing POI is flagged as a possible duplicate")
def test_a_poi_clicked_next_to_an_existing_poi_is_flagged_as_a_possible_duplicate() -> None:
    """Waits for slice 08 (D256)."""

"""The seed list ("Refresh map data" with no record) against the trimmed copy of the Geofabrik index (D315): it holds
the ids and addresses of the eight regions the map was first built from, and does not follow `make tiles-refresh`'s
`EXTRACTS`."""

from __future__ import annotations

import json
from pathlib import Path

from overland_planner.application.roadmap.facade import SEED_REGION_KEYS

INDEX = Path("tests/acceptance/overland_route_planner_mvp/fixtures/road-map/geofabrik-index-trimmed.json")
SEED_IDS = {
    "italy",
    "spain",
    "switzerland",
    "austria",
    "rhone-alpes",
    "provence-alpes-cote-d-azur",
    "languedoc-roussillon",
    "midi-pyrenees",
}


def test_the_seed_ids_are_the_eight_regions_and_each_has_its_addresses_in_the_index() -> None:
    features = {f["properties"]["id"]: f["properties"] for f in json.loads(INDEX.read_text())["features"]}
    assert set(SEED_REGION_KEYS) == SEED_IDS and len(SEED_REGION_KEYS) == len(SEED_IDS)
    for key in SEED_REGION_KEYS:
        urls = features[key]["urls"]
        assert urls["pbf"].endswith(f"/{key}-latest.osm.pbf"), key
        assert urls["poly"].endswith(f"/{key}.poly"), key

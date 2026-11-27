"""Geofabrik .poly parsing (D302): real fixtures into Outlines, faults into one named error.

Driving port: `parse_poly(text)`. Observable universe = the Outline or the PolyParseError.
Test Budget: 3 behaviors (real fixtures parse, holes are recognised, each fault is refused) x 2 = 6; 4 used.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.adapters.roadmap.poly_parser import PolyParseError, parse_poly
from overland_planner.domain.catalog.coordinate import Coordinate

POLY_DIR = Path(__file__).resolve().parents[3] / "acceptance/overland_route_planner_mvp/fixtures/road-map/poly"
POINT_INSIDE = {
    "italy": (12.5, 42.0),
    "spain": (-3.7, 40.4),
    "switzerland": (8.2, 46.8),
    "austria": (14.0, 47.5),
    "rhone-alpes": (5.0, 45.5),
    "provence-alpes-cote-d-azur": (6.0, 43.9),
    "languedoc-roussillon": (3.3, 43.6),
    "midi-pyrenees": (1.4, 43.6),
    "portugal": (-8.0, 39.5),
    "andorra": (1.55, 42.55),
    "utah": (-111.5, 39.5),
}


@pytest.mark.parametrize("name", sorted(POINT_INSIDE))
def test_every_fixture_parses_into_an_outline_that_holds_its_region(name):
    lon, lat = POINT_INSIDE[name]
    outline = parse_poly((POLY_DIR / f"{name}.poly").read_text())
    assert outline.contains(Coordinate(latitude=lat, longitude=lon))
    assert not outline.contains(Coordinate(latitude=-60.0, longitude=0.0))


@given(st.integers(1, 3), st.integers(1, 3))
def test_bang_rings_are_holes_and_plain_rings_are_outlines(outers, holes):
    square = "   0.0   0.0\n   9.0   0.0\n   9.0   9.0\n   0.0   9.0\n   0.0   0.0\nEND\n"
    sections = [f"{i + 1}\n{square}" for i in range(outers)] + [f"!{outers + i + 1}\n{square}" for i in range(holes)]
    outline = parse_poly("name\n" + "".join(sections) + "END\n")
    assert (len(outline.rings), len(outline.holes)) == (outers, holes)


@pytest.mark.parametrize(
    "text",
    [
        "x\n1\n 0 0\n 1 0\n 1 1\n 0 0\nEND\n",  # no closing END for the file
        "x\n1\n 0 0\n 1 0\n 1 1\n 0 0\n",  # no closing END at all
        "x\n1\n 0 0\n 1 0\nEND\nEND\n",  # a ring of fewer than 3 points
        "x\n1\n 0 0\n 1 north\n 1 1\nEND\nEND\n",  # a non-numeric point
        "x\n1\n 0 0\n 1\n 1 1\nEND\nEND\n",  # a point with one number
        "",  # empty
        "x\nEND\n",  # no ring at all
    ],
)
def test_malformed_files_raise_the_named_parse_error(text):
    # bypass: each fault is one named input class; there is no input space to generalise over
    with pytest.raises(PolyParseError):
        parse_poly(text)


def _coverage(names):
    from overland_planner.domain.roadmap.coverage import RoadMapCoverage

    return RoadMapCoverage(regions=tuple((n, parse_poly((POLY_DIR / f"{n}.poly").read_text())) for n in names))


def test_real_borders_link_italy_and_spain_only_through_the_two_occitanie_regions():
    # bypass: two fixed real-border facts from the owner's map (AC 4), not a rule over generated inputs
    base = ["italy", "spain", "rhone-alpes", "provence-alpes-cote-d-azur"]
    occitanie = ["languedoc-roussillon", "midi-pyrenees"]
    eight = [*base, *occitanie, "austria", "switzerland"]
    with_all = _coverage(eight)
    without = _coverage([*base, "austria", "switzerland"])
    assert [g for g in with_all.land_groups() if "spain" in g and "italy" in g]
    assert [g for g in without.land_groups() if "spain" in g] == [("spain",)]
    assert not with_all.contains(Coordinate(latitude=42.5063, longitude=1.5218))

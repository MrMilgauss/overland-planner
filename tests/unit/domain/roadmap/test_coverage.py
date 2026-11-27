"""Road-map coverage (D302): containment over all loaded regions, land groups as connected components.

Driving port: `RoadMapCoverage.contains` and `RoadMapCoverage.land_groups`. Observable universe = the answer.
Test Budget: 3 behaviors (contains any region, groups partition and are symmetric, touching/crossing joins and
disjoint separates) x 2 = 6; 4 used.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.roadmap.coverage import RoadMapCoverage
from overland_planner.domain.roadmap.outline import Outline


def box(x0: int, y0: int, size: int) -> Outline:
    pts = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)]
    return Outline(rings=(tuple(Coordinate(latitude=y, longitude=x) for x, y in pts),))


@st.composite
def coverages(draw):
    n = draw(st.integers(1, 6))
    names = draw(st.lists(st.text("abcdefgh", min_size=1, max_size=3), min_size=n, max_size=n, unique=True))
    boxes = [box(draw(st.integers(-40, 40)), draw(st.integers(-40, 40)), draw(st.integers(1, 12))) for _ in names]
    return RoadMapCoverage(regions=tuple(zip(names, boxes, strict=True)))


@given(coverages(), st.integers(-60, 60), st.integers(-60, 60))
def test_a_point_is_covered_when_any_region_holds_it(coverage, lon, lat):
    point = Coordinate(latitude=lat, longitude=lon)
    assert coverage.contains(point) == any(o.contains(point) for _, o in coverage.regions)


@given(coverages(), st.randoms(use_true_random=False))
def test_groups_partition_the_regions_whatever_their_order(coverage, rnd):
    shuffled = list(coverage.regions)
    rnd.shuffle(shuffled)
    groups = coverage.land_groups()
    flat = [name for group in groups for name in group]
    assert sorted(flat) == sorted(name for name, _ in coverage.regions)
    assert all(list(g) == sorted(g) for g in groups)
    assert groups == RoadMapCoverage(regions=tuple(shuffled)).land_groups()
    assert list(groups) == sorted(groups)


@given(st.integers(-40, 40), st.integers(-40, 40), st.integers(2, 12), st.integers(1, 10))
def test_regions_that_share_a_vertex_or_cross_are_one_group_and_disjoint_ones_are_apart(x0, y0, size, gap):
    shares_vertex = box(x0 + size, y0 + size, size)
    crossing = Outline(
        rings=(
            tuple(
                Coordinate(latitude=y, longitude=x)
                for x, y in [
                    (x0 + 1, y0 - 1),
                    (x0 + size - 1, y0 - 1),
                    (x0 + size - 1, y0 + size + 1),
                    (x0 + 1, y0 + size + 1),
                ]
            ),
        )
    )
    far = box(x0 + size + gap, y0 + size + gap + size, size)
    coverage = RoadMapCoverage(
        regions=(("c-base", box(x0, y0, size)), ("a-vertex", shares_vertex), ("b-cross", crossing), ("z-far", far))
    )
    assert coverage.land_groups() == (("a-vertex", "b-cross", "c-base"), ("z-far",))


@given(st.integers(-40, 40), st.integers(-40, 40), st.integers(2, 12))
def test_linking_is_transitive_through_a_middle_region(x0, y0, size):
    chain = RoadMapCoverage(
        regions=(("end", box(x0 + 2 * size, y0, size)), ("start", box(x0, y0, size)), ("mid", box(x0 + size, y0, size)))
    )
    assert chain.land_groups() == (("end", "mid", "start"),)

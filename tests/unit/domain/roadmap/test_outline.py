"""Outline containment (D302): even-odd over rings and holes, the boundary counts as inside.

Driving port: `Outline.contains` and `Outline.touches` (pure domain value). Observable universe = the boolean answer.
Test Budget: 4 behaviors (inside, hole outside, boundary inside, translation invariance) + touches (1) = 5 x 2 = 10;
7 used. Coordinates are whole numbers so every comparison is exact.
"""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.roadmap.outline import Outline

SPAN = st.integers(min_value=-40, max_value=40)


def ring(*lonlat: tuple[float, float]) -> tuple[Coordinate, ...]:
    return tuple(Coordinate(latitude=lat, longitude=lon) for lon, lat in lonlat)


def rect(x0: float, y0: float, x1: float, y1: float) -> tuple[Coordinate, ...]:
    return ring((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def at(lon: float, lat: float) -> Coordinate:
    return Coordinate(latitude=lat, longitude=lon)


@st.composite
def holed_rectangles(draw):
    x0, y0 = draw(SPAN), draw(SPAN)
    w, h = draw(st.integers(4, 30)), draw(st.integers(4, 30))
    hole = rect(x0 + 1, y0 + 1, x0 + w - 1, y0 + h - 1)
    return x0, y0, w, h, Outline(rings=(rect(x0, y0, x0 + w, y0 + h),), holes=(hole,))


@given(holed_rectangles(), st.data())
def test_a_point_between_outer_ring_and_hole_is_inside(shape, data):
    x0, y0, w, h, outline = shape
    # the one-unit band between outer ring and hole, off both edges: the half-unit lines
    lon = data.draw(st.sampled_from([x0 + 0.5, x0 + w - 0.5]))
    lat = data.draw(st.integers(y0, y0 + h))
    assert outline.contains(at(lon, lat))


@given(holed_rectangles(), st.data())
def test_a_point_in_the_hole_or_beyond_the_ring_is_outside(shape, data):
    x0, y0, w, h, outline = shape
    in_hole = at(x0 + 1.5, y0 + 1.5)
    beyond = data.draw(
        st.sampled_from([at(x0 - 1, y0 + 2), at(x0 + w + 1, y0 + 2), at(x0 + 2, y0 - 1), at(x0 + 2, y0 + h + 1)])
    )
    assert (outline.contains(in_hole), outline.contains(beyond)) == (False, False)


@given(SPAN, SPAN, st.integers(1, 20), st.data())
def test_vertices_and_edge_points_are_inside(x0, y0, k, data):
    square = Outline(rings=(rect(x0, y0, x0 + 2 * k, y0 + 2 * k),))
    triangle = Outline(rings=(ring((x0, y0), (x0 + 2 * k, y0), (x0, y0 + 2 * k)),))
    i = data.draw(st.integers(0, 2 * k))
    on_square_edges = [at(x0 + i, y0), at(x0 + i, y0 + 2 * k), at(x0, y0 + i), at(x0 + 2 * k, y0 + i)]
    on_hypotenuse = at(x0 + i, y0 + 2 * k - i)
    assert all(square.contains(p) for p in on_square_edges)
    assert triangle.contains(on_hypotenuse)
    assert triangle.contains(at(x0, y0 + 2 * k))
    assert not triangle.contains(at(x0 + i + 1, y0 + 2 * k - i + 1))


@given(SPAN, SPAN, st.integers(2, 20), st.integers(-30, 30), st.integers(-30, 30), SPAN, SPAN, st.integers(-30, 30))
def test_translating_ring_and_point_together_keeps_the_answer(x0, y0, size, px, py, dx, dy, _unused):
    # whole-number shifts of a ring with a hole, so the shifted copy is exact
    base = Outline(
        rings=(rect(x0, y0, x0 + size, y0 + size),), holes=(rect(x0 + 1, y0 + 1, x0 + size - 1, y0 + size - 1),)
    )
    point = at(x0 + px / 2, y0 + py / 2)
    assume(abs(point.longitude + dx) <= 170 and abs(point.latitude + dy) <= 80)
    assume(all(abs(c.longitude + dx) <= 170 and abs(c.latitude + dy) <= 80 for r in base.rings + base.holes for c in r))
    moved = Outline(
        rings=tuple(tuple(at(c.longitude + dx, c.latitude + dy) for c in r) for r in base.rings),
        holes=tuple(tuple(at(c.longitude + dx, c.latitude + dy) for c in r) for r in base.holes),
    )
    assert moved.contains(at(point.longitude + dx, point.latitude + dy)) == base.contains(point)


@given(SPAN, SPAN, st.integers(2, 20), st.integers(1, 19))
def test_outlines_touch_when_a_vertex_is_shared_or_edges_cross_or_one_holds_the_other(x0, y0, size, shift):
    shift = min(shift, size - 1)
    a = Outline(rings=(rect(x0, y0, x0 + size, y0 + size),))
    sharing_a_corner = Outline(rings=(rect(x0 + size, y0 + size, x0 + 2 * size, y0 + 2 * size),))
    overlapping = Outline(rings=(rect(x0 + shift, y0 + shift, x0 + size + shift, y0 + size + shift),))
    crossing = Outline(rings=(rect(x0 + 1, y0 - 1, x0 + size - 1, y0 + size + 1),))  # a cross: no vertex inside
    inside = Outline(rings=(rect(x0 + 1, y0 + 1, x0 + size - 1, y0 + size - 1),))
    assert all(a.touches(o) and o.touches(a) for o in (sharing_a_corner, overlapping, crossing, inside))


@given(SPAN, SPAN, st.integers(2, 20), st.integers(1, 10))
def test_outlines_with_a_gap_between_do_not_touch(x0, y0, size, gap):
    a = Outline(rings=(rect(x0, y0, x0 + size, y0 + size),))
    right = Outline(rings=(rect(x0 + size + gap, y0, x0 + 2 * size + gap, y0 + size),))
    above = Outline(rings=(rect(x0, y0 + size + gap, x0 + size, y0 + 2 * size + gap),))
    assert not any(a.touches(o) or o.touches(a) for o in (right, above))

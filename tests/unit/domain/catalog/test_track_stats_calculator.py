"""Track statistics (brief §4, US-02a): length, entry and exit of a recorded track, in recorded order (HC-1).

Driving port: the pure domain service `TrackStatsCalculator.calculate(points)` and the `TrackPoint.at(...)` value
constructor (their signatures are the public interface; wiring into import is proved at 03-05).
Test Budget: 5 behaviors (great-circle length, length invariants under reversal and split, entry/exit in recorded
order, out-of-range refusal, short track unusable) x 2 = 10; 7 property tests used.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import CoordinateOutOfRangeError
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.catalog.track_stats_calculator import TrackStats, TrackStatsCalculator
from tests.common.state_delta import assert_state_delta, set_to

STATS_UNIVERSE = {"usable", "length_m", "entry", "exit"}
NOT_YET_CALCULATED = {"usable": None, "length_m": None, "entry": None, "exit": None}
# IUGG mean Earth radius R1, the documented choice of the calculator; used here only to turn meridian degrees into
# metres (an arc along a meridian is R * delta-latitude, independent of any great-circle formula).
MEAN_EARTH_RADIUS_M = 6_371_008.8

ELEVATION = st.none() | st.floats(min_value=-430.0, max_value=4_810.0)
ALPINE_POINT = st.builds(
    TrackPoint.at,
    latitude=st.floats(min_value=44.0, max_value=48.0),
    longitude=st.floats(min_value=5.0, max_value=17.0),
    elevation_m=ELEVATION,
)
ALPINE_TRACK = st.lists(ALPINE_POINT, min_size=2, max_size=40)


def _stats(points: list[TrackPoint]) -> dict[str, Any]:
    result = TrackStatsCalculator().calculate(points)
    if isinstance(result, TrackStats):
        return {"usable": True, "length_m": result.length_m, "entry": result.entry, "exit": result.exit}
    return {"usable": False, "length_m": None, "entry": None, "exit": None}


def _close_to(expected: float) -> Callable[[Any, float], bool]:
    return lambda _before, after: math.isclose(after, expected, rel_tol=1e-9, abs_tol=1e-6)


def _meridian_track(fixed: float, moving: list[float]) -> tuple[list[TrackPoint], float]:
    return [TrackPoint.at(lat, fixed) for lat in moving], MEAN_EARTH_RADIUS_M * math.radians(moving[-1] - moving[0])


def _equator_track(_fixed: float, moving: list[float]) -> tuple[list[TrackPoint], float]:
    return [TrackPoint.at(0.0, lon) for lon in moving], MEAN_EARTH_RADIUS_M * math.radians(moving[-1] - moving[0])


# Along a meridian or the equator a monotone track is a great-circle arc of R * delta-angle: an oracle from geometry,
# independent of the haversine formula.
@given(
    along=st.sampled_from([_meridian_track, _equator_track]),
    fixed=st.floats(min_value=5.0, max_value=17.0),
    moving=st.lists(st.floats(min_value=44.0, max_value=48.0), min_size=2, max_size=20).map(sorted),
)
def test_length_along_a_great_circle_is_the_arc_between_entry_and_exit(
    along: Callable[[float, list[float]], tuple[list[TrackPoint], float]], fixed: float, moving: list[float]
) -> None:
    points, arc_m = along(fixed, moving)
    expected = {
        "usable": set_to(True),
        "length_m": _close_to(arc_m),
        "entry": set_to(points[0]),
        "exit": set_to(points[-1]),
    }
    assert_state_delta(NOT_YET_CALCULATED, _stats(points), STATS_UNIVERSE, expected, strict=True)


@given(points=ALPINE_TRACK)
def test_length_is_never_shorter_than_the_direct_distance_from_entry_to_exit(points: list[TrackPoint]) -> None:
    direct_m = _stats([points[0], points[-1]])["length_m"]
    after = _stats(points)
    assert direct_m >= 0.0
    assert_state_delta(
        NOT_YET_CALCULATED,
        after,
        STATS_UNIVERSE,
        {
            "usable": set_to(True),
            "length_m": lambda _b, a: a >= direct_m - 1e-6,
            "entry": set_to(points[0]),
            "exit": set_to(points[-1]),
        },
        strict=True,
    )


@given(points=ALPINE_TRACK)
def test_length_is_unchanged_by_reversal(points: list[TrackPoint]) -> None:
    recorded = _stats(points)
    reversed_track = _stats(list(reversed(points)))
    expected = {
        "length_m": _close_to(recorded["length_m"]),
        "entry": set_to(points[-1]),
        "exit": set_to(points[0]),
    }
    assert_state_delta(recorded, reversed_track, STATS_UNIVERSE, expected, strict=True)


@given(points=st.lists(ALPINE_POINT, min_size=3, max_size=40), data=st.data())
def test_length_is_additive_under_split(points: list[TrackPoint], data: st.DataObject) -> None:
    # split at any interior point: both halves keep that point and at least two points each
    split = data.draw(st.integers(min_value=1, max_value=len(points) - 2), label="split index")
    head = _stats(points[: split + 1])
    tail_length_m = _stats(points[split:])["length_m"]
    whole = _stats(points)
    expected = {"length_m": _close_to(head["length_m"] + tail_length_m), "exit": set_to(points[-1])}
    assert_state_delta(head, whole, STATS_UNIVERSE, expected, strict=True)


@given(points=ALPINE_TRACK)
def test_entry_and_exit_are_first_and_last_points(points: list[TrackPoint]) -> None:
    before = list(points)
    after = _stats(points)
    assert points == before  # the recorded order is never touched (HC-1)
    expected = {
        "usable": set_to(True),
        "length_m": lambda _b, a: a >= 0.0,
        "entry": set_to(points[0]),
        "exit": set_to(points[-1]),
    }
    assert_state_delta(NOT_YET_CALCULATED, after, STATS_UNIVERSE, expected, strict=True)


def _out_of_range(bound: float) -> st.SearchStrategy[float]:
    just_outside = st.sampled_from([math.nextafter(bound, math.inf), math.nextafter(-bound, -math.inf)])
    return just_outside | st.floats(min_value=bound, exclude_min=True) | st.floats(max_value=-bound, exclude_max=True)


OUT_OF_RANGE_LATITUDE = _out_of_range(90.0)
OUT_OF_RANGE_LONGITUDE = _out_of_range(180.0)
IN_RANGE_LATITUDE = st.floats(min_value=-90.0, max_value=90.0)
IN_RANGE_LONGITUDE = st.floats(min_value=-180.0, max_value=180.0)


def _point_outcome(latitude: float, longitude: float, elevation_m: float | None = None) -> dict[str, Any]:
    try:
        point = TrackPoint.at(latitude, longitude, elevation_m)
    except CoordinateOutOfRangeError:
        return {"point": None, "refused": True}
    return {"point": (point.coordinate.latitude, point.coordinate.longitude, point.elevation_m), "refused": False}


@given(
    coordinates=st.one_of(
        st.tuples(OUT_OF_RANGE_LATITUDE | st.just(math.nan), IN_RANGE_LONGITUDE),
        st.tuples(IN_RANGE_LATITUDE, OUT_OF_RANGE_LONGITUDE | st.just(math.nan)),
    ),
    valid=st.tuples(st.sampled_from([-90.0, 90.0]) | IN_RANGE_LATITUDE, st.sampled_from([-180.0, 180.0]), ELEVATION),
)
def test_out_of_range_point_is_refused(
    coordinates: tuple[float, float], valid: tuple[float, float, float | None]
) -> None:
    universe = {"point", "refused"}
    before = {"point": None, "refused": False}
    assert_state_delta(before, _point_outcome(*coordinates), universe, {"refused": set_to(True)}, strict=True)
    # the range bounds themselves are inclusive and accepted, elevation kept as recorded
    assert_state_delta(before, _point_outcome(*valid), universe, {"point": set_to(valid)}, strict=True)
    with pytest.raises(CoordinateOutOfRangeError) as refusal:  # a domain refusal, never a silently clamped point
        TrackPoint.at(*coordinates)
    assert str(refusal.value) == f"Coordinate out of range: latitude {coordinates[0]}, longitude {coordinates[1]}"


@given(points=st.lists(ALPINE_POINT, max_size=1))
def test_fewer_than_two_points_is_unusable(points: list[TrackPoint]) -> None:
    result = TrackStatsCalculator().calculate(points)
    assert not isinstance(result, TrackStats)
    assert (result.point_count, result.reason) == (len(points), "A track needs at least two points")
    assert_state_delta(NOT_YET_CALCULATED, _stats(points), STATS_UNIVERSE, {"usable": set_to(False)}, strict=True)

"""Coordinate (US-02c, D151): accepted iff -90 <= latitude <= 90 and -180 <= longitude <= 180, bounds included.

Driving port: the `Coordinate` value object itself (pure domain). Observable universe: the accepted coordinate and the
refusal message Marco would read; latitude is checked before longitude when both are wrong.
Test Budget: 1 behavior (range rule with its reasons) x 2 = 2; 1 used.
"""

from __future__ import annotations

import math
from typing import Any

from hypothesis import example, given
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate, CoordinateOutOfRangeError
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"coordinate", "refusal"}
LATITUDE_REASON = "Latitude must be between -90 and 90"
LONGITUDE_REASON = "Longitude must be between -180 and 180"
DEGREES = st.floats(min_value=-200.0, max_value=200.0) | st.floats()


def _outcome(latitude: float, longitude: float) -> dict[str, Any]:
    try:
        coordinate = Coordinate(latitude, longitude)
    except CoordinateOutOfRangeError as refusal:
        return {"coordinate": None, "refusal": str(refusal)}
    return {"coordinate": (coordinate.latitude, coordinate.longitude), "refusal": None}


@given(latitude=DEGREES, longitude=DEGREES)
@example(latitude=90.0, longitude=180.0)
@example(latitude=-90.0, longitude=-180.0)
@example(latitude=math.nextafter(90.0, math.inf), longitude=0.0)
@example(latitude=math.nextafter(-90.0, -math.inf), longitude=0.0)
@example(latitude=0.0, longitude=math.nextafter(180.0, math.inf))
@example(latitude=0.0, longitude=math.nextafter(-180.0, -math.inf))
@example(latitude=144.899, longitude=180.0001)
@example(latitude=math.nan, longitude=0.0)
@example(latitude=0.0, longitude=math.nan)
def test_a_coordinate_is_accepted_iff_both_degrees_are_within_the_inclusive_ranges(
    latitude: float, longitude: float
) -> None:
    latitude_ok, longitude_ok = -90.0 <= latitude <= 90.0, -180.0 <= longitude <= 180.0
    if not latitude_ok:
        expected = {"refusal": set_to(LATITUDE_REASON)}
    elif not longitude_ok:
        expected = {"refusal": set_to(LONGITUDE_REASON)}
    else:
        expected = {"coordinate": set_to((latitude, longitude))}

    before = {"coordinate": None, "refusal": None}
    assert_state_delta(before, _outcome(latitude, longitude), UNIVERSE, expected, strict=True)

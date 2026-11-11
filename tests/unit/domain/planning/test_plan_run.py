"""The totals of a plan (FR-6.2, ADR-017 section 3): road legs on one side, tracks and retraces off-road on the other.

Driving port: `Totals.of(stops)`, pure. A retrace is the track driven back, so its km and time are off-road at the
track's length; no stop kind adds a key or a penalty. Oracles are sums worked out here from the stops' own fields.
Test Budget: 1 behavior (the totals of any stops, whatever their order) x 2 = 2; 1 used.
"""

from __future__ import annotations

import math
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.planning.plan_run import PlanStop, Totals
from tests.common.state_delta import assert_state_delta, set_to

km = st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False)
seconds = st.floats(min_value=0.0, max_value=100_000.0, allow_nan=False, allow_infinity=False)


@st.composite
def stops_of_any_kind(draw: st.DrawFn) -> PlanStop:
    kind = draw(st.sampled_from(("poi", "track", "retrace")))
    has_leg = draw(st.booleans()) and kind != "retrace"  # a retrace is not a road leg
    return PlanStop(
        item_id="i",
        name="n",
        kind=kind,
        leg_km=draw(km) if has_leg else None,
        leg_s=draw(st.integers(0, 100_000)) if has_leg else None,
        track_km=draw(km) if kind != "poi" else None,
        offroad_s=draw(seconds) if kind != "poi" else None,
    )


@given(stops=st.lists(stops_of_any_kind(), min_size=1, max_size=12), data=st.data())
def test_totals_count_road_legs_as_road_and_tracks_and_retraces_as_offroad_whatever_the_order(
    stops: list[PlanStop], data: st.DataObject
) -> None:
    shuffled = data.draw(st.permutations(stops))
    universe = {"stops.read", "totals"}
    before: dict[str, Any] = {"stops.read": tuple(stops), "totals": None}

    totals = Totals.of(shuffled)

    road_km = math.fsum(s.leg_km or 0.0 for s in stops)
    road_s = sum(s.leg_s or 0 for s in stops)
    offroad_km = math.fsum(s.track_km or 0.0 for s in stops if s.kind != "poi")
    offroad_s = math.fsum(s.offroad_s or 0.0 for s in stops if s.kind != "poi")
    total_km = math.fsum([s.leg_km or 0.0 for s in stops] + [s.track_km or 0.0 for s in stops])
    total_s = math.fsum([s.leg_s or 0 for s in stops] + [s.offroad_s or 0.0 for s in stops])
    expected = Totals(road_km, road_s, offroad_km, offroad_s, total_km, total_s)
    after = {"stops.read": tuple(stops), "totals": totals}
    assert_state_delta(before, after, universe, {"totals": set_to(expected)}, strict=True)

"""A leg's kilometres, pinned by hand: the job's tests compute theirs with the same formula, so this holds it down.

Driving port: `LegTable.distance_km`.
Test Budget: 1 behavior (metres read as kilometres) x 2 = 2; 1 used.
"""

from __future__ import annotations

import pytest

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg

TORINO = Coordinate(45.0703, 7.6869)
BRIANCON = Coordinate(44.8986, 6.6419)


# bypass: no property - a generated expectation would repeat the formula; these literals are worked out by hand.
@pytest.mark.parametrize(
    ("metres", "origin", "destination", "kilometres"),
    [(1500, TORINO, BRIANCON, 1.5), (0, TORINO, BRIANCON, 0.0), (1500, TORINO, TORINO, 0.0)],
    ids=["1500-m", "a-leg-of-0-m", "identical-points"],
)
def test_a_leg_reads_in_kilometres(metres: int, origin: Coordinate, destination: Coordinate, kilometres: float) -> None:
    legs = LegTable([RoadLeg(TORINO, BRIANCON, metres)])

    assert legs.distance_km(origin, destination) == kilometres

"""The offline road map (brief section 6): straight line x 1.3, proven by its start-up probe on a known pair.

Integration level: single examples verify the adapter against its port contract. The expected distance is the pair's
figure computed once with an independent haversine, not with the adapter's own arithmetic.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from overland_planner.adapters.routing.mock_routing_provider import MockRoutingProvider
from overland_planner.domain.catalog.coordinate import Coordinate

TORINO = Coordinate(45.0703, 7.6869)
SUSA = Coordinate(45.1383, 7.0500)
AOSTA = Coordinate(45.7372, 7.3206)
TORINO_SUSA_STRAIGHT_M = 50_555  # haversine on the mean Earth radius


def test_road_legs_are_the_straight_line_times_1_3() -> None:
    provider = MockRoutingProvider()

    (row,) = provider.matrix([TORINO], [SUSA, AOSTA])

    assert row[0] == pytest.approx(TORINO_SUSA_STRAIGHT_M * 1.3, abs=1)
    assert row[1] == round(TORINO.great_circle_distance_m(AOSTA) * 1.3)
    assert all(isinstance(distance, int) for distance in row)


def test_identical_points_are_zero_metres_apart() -> None:
    assert MockRoutingProvider().matrix([TORINO, SUSA], [TORINO, SUSA])[1][1] == 0


def test_the_provider_id_names_the_road_map() -> None:
    assert MockRoutingProvider().provider_id == "mock:straight_line_x1.3"


def test_the_probe_passes_on_the_known_pair() -> None:
    result = MockRoutingProvider().probe()

    assert (result.outcome, result.reason) == ("ok", None)


def test_a_road_map_with_the_wrong_detour_factor_refuses_the_start() -> None:
    result = MockRoutingProvider(detour_factor=1.0).probe()

    assert (result.outcome, result.reason) == ("fatal", "routing_known_pair_wrong")


class _NoZeroForIdenticalPoints(MockRoutingProvider):
    def matrix(self, sources: Sequence[Coordinate], targets: Sequence[Coordinate]) -> Sequence[Sequence[int]]:
        return [[max(cell, 1) for cell in row] for row in super().matrix(sources, targets)]


def test_a_road_map_that_drives_between_identical_points_refuses_the_start() -> None:
    result = _NoZeroForIdenticalPoints().probe()

    assert (result.outcome, result.reason) == ("fatal", "routing_identical_points_not_zero")

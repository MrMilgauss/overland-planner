"""`RoutingProvider` offline (brief section 6): every road leg is the straight line x the detour factor, in metres.

The start-up probe proves that on a known pair, Torino to Susa, and that identical points are 0 m apart. Scripted faults
and per-pair levels (`MOCK_PLAN`) arrive with slice 06a.
"""

from __future__ import annotations

from collections.abc import Sequence

from overland_planner.application.ports.probe import ProbeCheck, ProbeResult, first_failure
from overland_planner.domain.catalog.coordinate import Coordinate

DETOUR_FACTOR = 1.3
_TORINO = Coordinate(45.0703, 7.6869)
_SUSA = Coordinate(45.1383, 7.0500)
_TORINO_SUSA_ROAD_M = 65_721  # 50 554.67 m straight (haversine, mean Earth radius) x 1.3
_KNOWN_PAIR_TOLERANCE_M = 1


class MockRoutingProvider:
    def __init__(self, detour_factor: float = DETOUR_FACTOR) -> None:
        self._detour_factor = detour_factor

    @property
    def provider_id(self) -> str:
        return f"mock:straight_line_x{self._detour_factor}"

    def matrix(self, sources: Sequence[Coordinate], targets: Sequence[Coordinate]) -> Sequence[Sequence[int]]:
        return [[self._road_m(source, target) for target in targets] for source in sources]

    def probe(self) -> ProbeResult:
        """Fatal when it fails: nothing here can recover by itself, so a wrong answer is a defect (brief section 7)."""
        return first_failure(
            (
                ProbeCheck("routing_known_pair_wrong", self._knows_the_pair),
                ProbeCheck("routing_identical_points_not_zero", self._identical_points_are_zero),
            ),
            failing_errors=(),
        )

    def _road_m(self, source: Coordinate, target: Coordinate) -> int:
        return round(source.great_circle_distance_m(target) * self._detour_factor)

    def _knows_the_pair(self) -> bool:
        (row,) = self.matrix([_TORINO], [_SUSA])
        return abs(row[0] - _TORINO_SUSA_ROAD_M) <= _KNOWN_PAIR_TOLERANCE_M

    def _identical_points_are_zero(self) -> bool:
        (row,) = self.matrix([_SUSA], [_SUSA])
        return row[0] == 0

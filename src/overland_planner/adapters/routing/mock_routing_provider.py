"""`RoutingProvider` offline (brief section 6): straight line x the detour factor, driven at 60 km/h, or a script.

Without a script every road leg is the straight line x 1.3 in metres, and its road time that distance at the one
default road speed (D220 f). A scripted road map (`MOCK_PLAN`, brief section 12) is a YAML file
`{detour_factor, pairs: [{from: [lat, lon], to: [lat, lon], distance_m, duration_s}]}`: each listed pair answers its
scripted distance and time (points matched at 6 decimals); every other pair keeps the default at the file's
detour_factor. The file is read once, at start-up, with `yaml.safe_load` only; a missing, unreadable or malformed file
(including a pair listed twice with different values) is `InvalidRoadMapError`, which names the path.
Identical points are always 0 m and 0 s apart, and distinct points never are.

`provider_id` names the road map: `mock:straight_line_x1.3`, plus `:script:<sha256 of the file>` when scripted.
The start-up probe proves Torino -> Susa (when the script does not list it), identical points, and that one scripted
pair answers as scripted. Snap classes, levels, unreachable points, the fault plan and latency arrive with slice 06a.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from overland_planner.application.ports.probe import ProbeCheck, ProbeResult, first_failure
from overland_planner.domain.catalog.coordinate import Coordinate, CoordinateOutOfRangeError
from overland_planner.domain.routing.road_leg import NOTHING_TO_DRIVE, RoadMeasure, RoadPair

DETOUR_FACTOR = 1.3
DEFAULT_ROAD_SPEED_KMH = 60
_METRES_PER_SECOND = DEFAULT_ROAD_SPEED_KMH * 1000 / 3600
_MATCH_DECIMALS = 6
_TORINO = Coordinate(45.0703, 7.6869)
_SUSA = Coordinate(45.1383, 7.0500)
_TORINO_SUSA_STRAIGHT_M = 50_554.67  # haversine, mean Earth radius
_TORINO_SUSA_ROAD_M = 65_721  # x 1.3
_KNOWN_PAIR_TOLERANCE_M = 1
_KNOWN_PAIR_TOLERANCE_S = 1
_PAIR_KEYS = frozenset({"from", "to", "distance_m", "duration_s"})
_TOP_LEVEL_KEYS = frozenset({"detour_factor", "pairs"})


class InvalidRoadMapError(ValueError):
    """The `MOCK_PLAN` road map cannot be used; the message names the file and the problem."""

    def __init__(self, path: Path, problem: str) -> None:
        super().__init__(f"road map {path}: {problem}")


@dataclass(frozen=True)
class RoadMapScript:
    """A parsed road map: the detour factor of unlisted pairs, the listed pairs, the sha256 of the file."""

    detour_factor: float
    pairs: Mapping[RoadPair, RoadMeasure]
    sha256: str


def read_road_map(path: Path) -> RoadMapScript:
    try:
        content = path.read_bytes()
        document = yaml.safe_load(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise InvalidRoadMapError(path, f"cannot be read ({type(error).__name__}: {error})") from None
    try:
        detour_factor, pairs = _parse(document)
    except (ValueError, TypeError) as error:
        raise InvalidRoadMapError(path, str(error)) from None
    return RoadMapScript(detour_factor, pairs, hashlib.sha256(content).hexdigest())


def _parse(document: object) -> tuple[float, dict[RoadPair, RoadMeasure]]:
    if not isinstance(document, dict) or not set(document) <= _TOP_LEVEL_KEYS or "pairs" not in document:
        raise ValueError("must be a mapping with `pairs` and an optional `detour_factor`")
    detour_factor = document.get("detour_factor", DETOUR_FACTOR)
    if not _is_number(detour_factor) or detour_factor < 1:
        raise ValueError("detour_factor must be a number of at least 1")
    listed = document["pairs"]
    if not isinstance(listed, list) or not listed:
        raise ValueError("pairs must be a non-empty list")
    pairs: dict[RoadPair, RoadMeasure] = {}
    for index, entry in enumerate(listed):
        pair, measure = _pair(index, entry)
        if pairs.setdefault(pair, measure) != measure:
            raise ValueError(f"pairs[{index}] lists a pair again with different values")
    return float(detour_factor), pairs


def _pair(index: int, entry: object) -> tuple[RoadPair, RoadMeasure]:
    if not isinstance(entry, dict) or set(entry) != _PAIR_KEYS:
        raise ValueError(f"pairs[{index}] must have exactly from, to, distance_m and duration_s")
    origin, destination = _point(index, entry["from"]), _point(index, entry["to"])
    if origin == destination:
        raise ValueError(f"pairs[{index}] goes from a point to itself, which is always 0 m and 0 s")
    distance_m, duration_s = entry["distance_m"], entry["duration_s"]
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (distance_m, duration_s)):
        raise ValueError(f"pairs[{index}] distance_m and duration_s must be whole numbers above 0")
    return (origin, destination), RoadMeasure(distance_m, duration_s)


def _point(index: int, value: object) -> Coordinate:
    if not isinstance(value, list) or len(value) != 2 or not all(_is_number(v) for v in value):
        raise ValueError(f"pairs[{index}] points must be [lat, lon]")
    try:
        return _matched(Coordinate(float(value[0]), float(value[1])))
    except CoordinateOutOfRangeError as error:
        raise ValueError(f"pairs[{index}]: {error}") from None


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _matched(point: Coordinate) -> Coordinate:
    return Coordinate(round(point.latitude, _MATCH_DECIMALS), round(point.longitude, _MATCH_DECIMALS))


class MockRoutingProvider:
    """The offline road map; with `script`, the script's detour factor replaces `detour_factor`."""

    def __init__(self, detour_factor: float = DETOUR_FACTOR, *, script: RoadMapScript | None = None) -> None:
        self._detour_factor = detour_factor if script is None else script.detour_factor
        self._script = script
        self._pairs: Mapping[RoadPair, RoadMeasure] = {} if script is None else script.pairs

    @property
    def provider_id(self) -> str:
        default = f"mock:straight_line_x{self._detour_factor}"
        return default if self._script is None else f"{default}:script:{self._script.sha256}"

    def matrix(self, sources: Sequence[Coordinate], targets: Sequence[Coordinate]) -> Sequence[Sequence[RoadMeasure]]:
        return [[self._measure(source, target) for target in targets] for source in sources]

    def probe(self) -> ProbeResult:
        """Fatal when it fails: nothing here can recover by itself, so a wrong answer is a defect (brief section 7)."""
        return first_failure(
            (
                ProbeCheck("routing_known_pair_wrong", self._knows_the_pair),
                ProbeCheck("routing_identical_points_not_zero", self._identical_points_are_zero),
                ProbeCheck("routing_scripted_pair_wrong", self._answers_its_script),
            ),
            failing_errors=(),
        )

    def _measure(self, source: Coordinate, target: Coordinate) -> RoadMeasure:
        if source == target:
            return NOTHING_TO_DRIVE
        scripted = self._pairs.get((_matched(source), _matched(target)))
        if scripted is not None:
            return scripted
        distance_m = max(1, round(source.great_circle_distance_m(target) * self._detour_factor))
        return RoadMeasure(distance_m, max(1, round(distance_m / _METRES_PER_SECOND)))

    def _knows_the_pair(self) -> bool:
        if (_TORINO, _SUSA) in self._pairs:
            return True
        expected_m = _TORINO_SUSA_ROAD_M if self._script is None else _TORINO_SUSA_STRAIGHT_M * self._detour_factor
        ((answered,),) = self.matrix([_TORINO], [_SUSA])
        expected_s = expected_m / _METRES_PER_SECOND
        distance_right = abs(answered.distance_m - expected_m) <= _KNOWN_PAIR_TOLERANCE_M
        return distance_right and abs(answered.duration_s - expected_s) <= _KNOWN_PAIR_TOLERANCE_S

    def _identical_points_are_zero(self) -> bool:
        ((answered,),) = self.matrix([_SUSA], [_SUSA])
        return answered == NOTHING_TO_DRIVE

    def _answers_its_script(self) -> bool:
        listed = next(iter(self._pairs.items()), None)
        if listed is None:
            return True
        (origin, destination), scripted = listed
        ((answered,),) = self.matrix([origin], [destination])
        return answered == scripted

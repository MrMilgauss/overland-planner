"""`RoutingProvider` offline (brief section 6): straight line x the detour factor, driven at 60 km/h, or a script.

Without a script every road leg is the straight line x 1.3 in metres, and its road time that distance at the one
default road speed (D220 f). A scripted road map (`MOCK_PLAN`, brief section 12) is a YAML file
`{detour_factor, pairs: [{from: [lat, lon], to: [lat, lon], distance_m, duration_s, level}], latency}`: each listed
pair answers its scripted distance and time (points matched at 6 decimals); every other pair keeps the default at the
file's detour_factor; `pairs` may be empty. The optional `level` (03b) is `confirmed` (the default),
`unconfirmed:<reason>` (distance and time as well, answered as an Unconfirmed measure with that reason) or `none`
(neither distance nor time: no road at any level, answered `None`); any other combination is refused. The file is read
once, at start-up, with `yaml.safe_load` only; a missing, unreadable or malformed file (including a pair listed twice
with different values or levels) is `InvalidRoadMapError`, which names the path.
Identical points are always 0 m and 0 s apart, and distinct points never are.

The optional `latency: {answered_at_once_pairs, then_each_call_s}` (06-09, brought forward from slice 06a) slows the
look-up: the pairs answered are counted over the road map's life, and once those answered before a matrix call have
reached `answered_at_once_pairs`, that call and every later one waits `then_each_call_s` before it answers. The probe's
calls are never delayed nor counted. The wait holds no lock, so calls may wait side by side.

The optional `off_network: [[lat, lon], ...]` (06a, D245) lists places no road open to vehicles reaches (points matched
at 6 decimals): every pair from or to one answers an `OffNetwork` naming that end or those ends, except a place to
itself; a malformed list is `InvalidRoadMapError`.

The optional `faults: {fail_after_pairs: N, fail_once_on_call: k, kind: unreachable|unavailable}` (06a, D248; `kind`
and at least one of the two) makes the engine's failures testable offline. The pairs answered and the matrix calls made
are counted over the road map's life, from its start or from `arm_faults`: once N pairs have been answered every later
call raises the typed error of `kind`; call number k is retried inside the road map, so it answers and the call's
observer hears one `retried()`. The probe's calls are never failed nor counted; a malformed plan is
`InvalidRoadMapError`. `arm_faults(None)` ends the faults.

`provider_id` names the road map: `mock:straight_line_x1.3`, plus `:script:<sha256 of the file>` when scripted (faults
included, as they are part of the file); arming faults later changes nothing of it, so the legs found stay known. Its
`profile` is `mock.v1`. The start-up probe proves Torino -> Susa (when the script does not list it), identical points,
that one scripted pair answers as scripted, that one pair of each level the script lists does and that one listed
off-network point answers so.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from overland_planner.application.ports.probe import ProbeCheck, ProbeResult, first_failure
from overland_planner.application.ports.routing_provider import (
    ProviderUnavailable,
    ProviderUnreachable,
    RoadCell,
    RoutingObserver,
    RoutingProviderError,
)
from overland_planner.domain.catalog.coordinate import Coordinate, CoordinateOutOfRangeError
from overland_planner.domain.routing.road_leg import NOTHING_TO_DRIVE, OffNetwork, RoadMeasure, RoadPair

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
_PAIR_KEYS = frozenset({"from", "to", "distance_m", "duration_s", "level"})
_PAIR_MANDATORY_KEYS = frozenset({"from", "to"})
_UNCONFIRMED_PREFIX = "unconfirmed:"
_TOP_LEVEL_KEYS = frozenset({"detour_factor", "pairs", "latency", "off_network", "faults"})
_FAULT_KEYS = frozenset({"fail_after_pairs", "fail_once_on_call", "kind"})
_FAILURES: dict[str, type[RoutingProviderError]] = {
    "unreachable": ProviderUnreachable,
    "unavailable": ProviderUnavailable,
}
PROFILE = "mock.v1"
_LATENCY_KEYS = frozenset({"answered_at_once_pairs", "then_each_call_s"})


class InvalidRoadMapError(ValueError):
    """The `MOCK_PLAN` road map cannot be used; the message names the file and the problem."""

    def __init__(self, path: Path, problem: str) -> None:
        super().__init__(f"road map {path}: {problem}")


@dataclass(frozen=True)
class RoadLookUpLatency:
    """How slow the look-up is: the pairs answered at once, then the wait of each further matrix call."""

    answered_at_once_pairs: int
    then_each_call_s: float


@dataclass(frozen=True)
class RoadMapFaults:
    """The scripted failures: after `fail_after_pairs` pairs answered every call fails, and call number
    `fail_once_on_call` is retried inside the road map; `kind` is the error, `unreachable` or `unavailable`."""

    kind: str
    fail_after_pairs: int | None = None
    fail_once_on_call: int | None = None


@dataclass(frozen=True)
class RoadMapScript:
    """A parsed road map: the detour factor of unlisted pairs, the listed pairs, the sha256 of the file, its latency and
    the places off the network."""

    detour_factor: float
    pairs: Mapping[RoadPair, RoadMeasure | None]
    sha256: str
    latency: RoadLookUpLatency | None = None
    off_network: frozenset[Coordinate] = frozenset()
    faults: RoadMapFaults | None = None


def read_road_map(path: Path) -> RoadMapScript:
    try:
        content = path.read_bytes()
        document = yaml.safe_load(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise InvalidRoadMapError(path, f"cannot be read ({type(error).__name__}: {error})") from None
    try:
        detour_factor, pairs, latency, off_network, faults = _parse(document)
    except (ValueError, TypeError) as error:
        raise InvalidRoadMapError(path, str(error)) from None
    return RoadMapScript(detour_factor, pairs, hashlib.sha256(content).hexdigest(), latency, off_network, faults)


def _parse(
    document: object,
) -> tuple[
    float, dict[RoadPair, RoadMeasure | None], RoadLookUpLatency | None, frozenset[Coordinate], RoadMapFaults | None
]:
    if not isinstance(document, dict) or not set(document) <= _TOP_LEVEL_KEYS or "pairs" not in document:
        raise ValueError("must be a mapping with `pairs` and an optional `detour_factor` and `latency`")
    detour_factor = document.get("detour_factor", DETOUR_FACTOR)
    if not _is_number(detour_factor) or detour_factor < 1:
        raise ValueError("detour_factor must be a number of at least 1")
    listed = document["pairs"]
    if not isinstance(listed, list):
        raise ValueError("pairs must be a list")
    pairs: dict[RoadPair, RoadMeasure | None] = {}
    for index, entry in enumerate(listed):
        pair, measure = _pair(index, entry)
        if pairs.setdefault(pair, measure) != measure:
            raise ValueError(f"pairs[{index}] lists a pair again with different values or levels")
    return (
        float(detour_factor),
        pairs,
        _latency(document.get("latency")),
        _off_network(document.get("off_network", [])),
        _faults(document.get("faults")),
    )


def _faults(value: object) -> RoadMapFaults | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not set(value) <= _FAULT_KEYS or value.get("kind") not in _FAILURES:
        raise ValueError(
            "faults must have a kind (unreachable or unavailable) and fail_after_pairs or fail_once_on_call"
        )
    after, once = value.get("fail_after_pairs"), value.get("fail_once_on_call")
    if after is None and once is None:
        raise ValueError("faults must have fail_after_pairs or fail_once_on_call")
    if after is not None and (not _is_whole(after) or after < 0):
        raise ValueError("faults fail_after_pairs must be a whole number of at least 0")
    if once is not None and (not _is_whole(once) or once < 1):
        raise ValueError("faults fail_once_on_call must be a whole number of at least 1")
    return RoadMapFaults(value["kind"], after, once)


def _is_whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _off_network(listed: object) -> frozenset[Coordinate]:
    if not isinstance(listed, list):
        raise ValueError("off_network must be a list of [lat, lon] points")
    return frozenset(_point(f"off_network[{index}]", value) for index, value in enumerate(listed))


def _latency(value: object) -> RoadLookUpLatency | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _LATENCY_KEYS:
        raise ValueError("latency must have exactly answered_at_once_pairs and then_each_call_s")
    pairs, seconds = value["answered_at_once_pairs"], value["then_each_call_s"]
    if not isinstance(pairs, int) or isinstance(pairs, bool) or pairs < 0:
        raise ValueError("latency answered_at_once_pairs must be a whole number of at least 0")
    if not _is_number(seconds) or seconds < 0:
        raise ValueError("latency then_each_call_s must be a number of at least 0")
    return RoadLookUpLatency(pairs, float(seconds))


def _pair(index: int, entry: object) -> tuple[RoadPair, RoadMeasure | None]:
    if not isinstance(entry, dict) or not _PAIR_MANDATORY_KEYS <= set(entry) <= _PAIR_KEYS:
        raise ValueError(f"pairs[{index}] must have from, to, distance_m, duration_s and an optional level")
    origin, destination = _point(index, entry["from"]), _point(index, entry["to"])
    if origin == destination:
        raise ValueError(f"pairs[{index}] goes from a point to itself, which is always 0 m and 0 s")
    return (origin, destination), _measure_of(index, entry)


def _measure_of(index: int, entry: dict[str, object]) -> RoadMeasure | None:
    level = entry.get("level", "confirmed")
    if not isinstance(level, str):
        raise ValueError(f"pairs[{index}] level must be text")
    figures = [entry.get("distance_m"), entry.get("duration_s")]
    if level == "none":
        if "distance_m" in entry or "duration_s" in entry:
            raise ValueError(f"pairs[{index}] at level none has no road, so neither distance_m nor duration_s")
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in figures):
        raise ValueError(f"pairs[{index}] distance_m and duration_s must be whole numbers above 0")
    distance_m, duration_s = cast(int, figures[0]), cast(int, figures[1])
    if level == "confirmed":
        return RoadMeasure(distance_m, duration_s)
    reason = level.removeprefix(_UNCONFIRMED_PREFIX)
    if not level.startswith(_UNCONFIRMED_PREFIX) or not reason.strip():
        raise ValueError(f"pairs[{index}] level must be confirmed, unconfirmed:<reason> or none")
    return RoadMeasure(distance_m, duration_s, level="unconfirmed", reason=reason)


def _point(where: int | str, value: object) -> Coordinate:
    place = f"pairs[{where}]" if isinstance(where, int) else where
    if not isinstance(value, list) or len(value) != 2 or not all(_is_number(v) for v in value):
        raise ValueError(f"{place} points must be [lat, lon]")
    try:
        return _matched(Coordinate(float(value[0]), float(value[1])))
    except CoordinateOutOfRangeError as error:
        raise ValueError(f"{place}: {error}") from None


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _matched(point: Coordinate) -> Coordinate:
    return Coordinate(round(point.latitude, _MATCH_DECIMALS), round(point.longitude, _MATCH_DECIMALS))


class _LookUpPace:
    """The script's latency over the road map's life: counts the pairs answered and says how long a call waits."""

    def __init__(self, latency: RoadLookUpLatency | None) -> None:
        self._latency = latency
        self._answered = 0
        self._lock = threading.Lock()
        self._probing = threading.local()

    def wait_s(self) -> float | None:
        """The wait of the next call, `None` when it answers at once."""
        if self._latency is None or getattr(self._probing, "on", False):
            return None
        with self._lock:
            reached = self._answered >= self._latency.answered_at_once_pairs
        return self._latency.then_each_call_s if reached else None

    def answered(self, pairs: int) -> None:
        if getattr(self._probing, "on", False):
            return
        with self._lock:
            self._answered += pairs

    def probing(self, on: bool) -> None:
        self._probing.on = on


class _FaultCourse:
    """The fault plan over the road map's life: counts the matrix calls and the pairs answered since it was armed, and
    fails or retries a call as the plan says. The probe's calls are never failed nor counted."""

    def __init__(self, faults: RoadMapFaults | None) -> None:
        self._faults = faults
        self._calls = 0
        self._answered = 0
        self._lock = threading.Lock()
        self._probing = threading.local()

    def probing(self, on: bool) -> None:
        self._probing.on = on

    def before_answering(self, observer: RoutingObserver | None) -> None:
        """Raises the typed error once the pairs answered have reached the plan; tells the observer of the one retry."""
        if self._faults is None or getattr(self._probing, "on", False):
            return
        with self._lock:
            self._calls += 1
            call, answered = self._calls, self._answered
        if self._faults.fail_after_pairs is not None and answered >= self._faults.fail_after_pairs:
            raise _FAILURES[self._faults.kind](f"scripted fault: {answered} pairs answered")
        if call == self._faults.fail_once_on_call and observer is not None:
            observer.retried()

    def answered(self, pairs: int) -> None:
        if getattr(self._probing, "on", False):
            return
        with self._lock:
            self._answered += pairs


class MockRoutingProvider:
    """The offline road map; with `script`, the script's detour factor replaces `detour_factor`; `sleep` waits out the
    script's latency."""

    def __init__(
        self,
        detour_factor: float = DETOUR_FACTOR,
        *,
        script: RoadMapScript | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._detour_factor = detour_factor if script is None else script.detour_factor
        self._script = script
        self._pairs: Mapping[RoadPair, RoadMeasure | None] = {} if script is None else script.pairs
        self._off_network = frozenset[Coordinate]() if script is None else script.off_network
        self._pace = _LookUpPace(None if script is None else script.latency)
        self._faults = _FaultCourse(None if script is None else script.faults)
        self._sleep = sleep

    def arm_faults(self, faults: RoadMapFaults | None) -> None:
        """Fail as `faults` say from now on, counting the calls and pairs from now; `None` ends the faults."""
        self._faults = _FaultCourse(faults)

    @property
    def provider_id(self) -> str:
        default = f"mock:straight_line_x{self._detour_factor}"
        return default if self._script is None else f"{default}:script:{self._script.sha256}"

    @property
    def profile(self) -> str:
        return PROFILE

    def matrix(
        self, sources: Sequence[Coordinate], targets: Sequence[Coordinate], observer: RoutingObserver | None = None
    ) -> Sequence[Sequence[RoadCell]]:
        faults = self._faults  # the plan of this call, even if it is re-armed while the call waits
        faults.before_answering(observer)
        wait_s = self._pace.wait_s()
        if wait_s is not None:
            self._sleep(wait_s)
        answer = [[self._measure(source, target) for target in targets] for source in sources]
        self._pace.answered(len(sources) * len(targets))
        faults.answered(len(sources) * len(targets))
        return answer

    def probe(self) -> ProbeResult:
        """Fatal when it fails: nothing here can recover by itself, so a wrong answer is a defect (brief section 7).
        Its calls are never delayed by the latency, nor counted."""
        self._pace.probing(True)
        self._faults.probing(True)
        try:
            return first_failure(
                (
                    ProbeCheck("routing_known_pair_wrong", self._knows_the_pair),
                    ProbeCheck("routing_identical_points_not_zero", self._identical_points_are_zero),
                    ProbeCheck("routing_scripted_pair_wrong", self._answers_its_script),
                    ProbeCheck("routing_scripted_level_wrong", self._answers_each_level_it_lists),
                    ProbeCheck("routing_off_network_wrong", self._answers_off_network_where_scripted),
                ),
                failing_errors=(),
            )
        finally:
            self._pace.probing(False)
            self._faults.probing(False)

    def _measure(self, source: Coordinate, target: Coordinate) -> RoadCell:
        if source == target:
            return NOTHING_TO_DRIVE
        named = frozenset(end for end in (source, target) if _matched(end) in self._off_network)
        if named:
            return OffNetwork(named)
        listed = (_matched(source), _matched(target))
        if listed in self._pairs:
            return self._pairs[listed]
        distance_m = max(1, round(source.great_circle_distance_m(target) * self._detour_factor))
        return RoadMeasure(distance_m, max(1, round(distance_m / _METRES_PER_SECOND)))

    def _knows_the_pair(self) -> bool:
        if (_TORINO, _SUSA) in self._pairs:
            return True
        expected_m = _TORINO_SUSA_ROAD_M if self._script is None else _TORINO_SUSA_STRAIGHT_M * self._detour_factor
        ((answered,),) = self.matrix([_TORINO], [_SUSA])
        if not isinstance(answered, RoadMeasure):
            return False
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

    def _answers_off_network_where_scripted(self) -> bool:
        """One listed off-network point answers off the network, named, towards a point that is not listed."""
        listed = next(iter(sorted(self._off_network, key=lambda p: (p.latitude, p.longitude))), None)
        if listed is None:
            return True
        elsewhere = _SUSA if _matched(_SUSA) not in self._off_network else _TORINO
        ((answered,),) = self.matrix([listed], [elsewhere])
        return answered == OffNetwork(frozenset({listed}))

    def _answers_each_level_it_lists(self) -> bool:
        """One listed pair of each level present (confirmed, unconfirmed, none) answers exactly as scripted."""
        firsts: dict[str, tuple[RoadPair, RoadMeasure | None]] = {}
        for pair, scripted in self._pairs.items():
            firsts.setdefault(_level_of(scripted), (pair, scripted))
        for (origin, destination), scripted in firsts.values():
            ((answered,),) = self.matrix([origin], [destination])
            if answered != scripted:
                return False
        return True


def _level_of(measure: RoadMeasure | None) -> str:
    return "none" if measure is None else measure.level

"""The offline road map (brief section 6): straight line x 1.3 at 60 km/h, or a scripted road map read from `MOCK_PLAN`.

Integration level: single examples verify the adapter against its port contract and against a real road-map file
(the DISTILL fixture of plan run #4, read from disk). The expected Torino -> Susa figures are computed once by hand
with an independent haversine, not with the adapter's own arithmetic: 50 554.67 m straight x 1.3 = 65 721 m, and
65 721 m at 60 km/h (16.667 m/s) = 3 943 s.

The look-up latency (06-09, brought forward from slice 06a): one property over the delay rule, with the adapter's sleep
replaced by a recorder so that no example sleeps, and one single example that really waits a fifth of a second.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.adapters.routing.mock_routing_provider import (
    InvalidRoadMapError,
    MockRoutingProvider,
    RoadLookUpLatency,
    RoadMapScript,
    read_road_map,
)
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import RoadMeasure
from tests.common.state_delta import assert_state_delta, set_to

REPO_ROOT = Path(__file__).resolve().parents[4]
PLAN_RUN_4 = REPO_ROOT / "tests/acceptance/overland_route_planner_mvp/fixtures/road-maps/plan-run-4.yaml"
TORINO = Coordinate(45.0703, 7.6869)  # also "Casa Marco, Torino" in the plan run #4 script
SUSA = Coordinate(45.1383, 7.0500)
AOSTA = Coordinate(45.7372, 7.3206)
PIAN_DELL_ALPE = Coordinate(45.056, 7.041)  # the Assietta's entry
TORINO_SUSA = RoadMeasure(distance_m=65_721, duration_s=3_943)
CASA_MARCO_ASSIETTA = RoadMeasure(distance_m=86_100, duration_s=5_100)  # as plan-run-4.yaml scripts it
ONE_PAIR = "pairs:\n  - {from: [45.0703, 7.6869], to: [45.056, 7.041], distance_m: 86100, duration_s: 5100}\n"


def test_road_legs_are_the_straight_line_times_1_3_driven_at_60_km_h() -> None:
    (row,) = MockRoutingProvider().matrix([TORINO], [SUSA, AOSTA])

    assert row[0] == TORINO_SUSA
    assert row[1].distance_m == round(TORINO.great_circle_distance_m(AOSTA) * 1.3)
    assert row[1].duration_s > 0
    assert all(isinstance(value, int) for cell in row for value in (cell.distance_m, cell.duration_s))


def test_identical_points_are_zero_metres_and_zero_seconds_apart() -> None:
    assert MockRoutingProvider().matrix([TORINO, SUSA], [TORINO, SUSA])[1][1] == RoadMeasure(0, 0)


def test_scripted_pair_answers_its_distance_and_time() -> None:
    provider = MockRoutingProvider(script=read_road_map(PLAN_RUN_4))

    (row,) = provider.matrix([Coordinate(45.0703, 7.6869)], [Coordinate(45.056, 7.041)])

    assert row == [CASA_MARCO_ASSIETTA]


def test_unlisted_pair_keeps_the_default() -> None:
    provider = MockRoutingProvider(script=read_road_map(PLAN_RUN_4))

    (row,) = provider.matrix([TORINO], [SUSA, TORINO])

    assert row == [TORINO_SUSA, RoadMeasure(0, 0)]


def _write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_text(text)
    return path


BAD_ROAD_MAPS = {
    "missing": lambda folder: folder / "absent.yaml",
    "unreadable": lambda folder: folder,  # a folder, not a file
    "not-yaml": lambda folder: _write(folder, "bad.yaml", "pairs: [unclosed\n"),
    "not-a-mapping": lambda folder: _write(folder, "bad.yaml", "- 1\n- 2\n"),
    "no-road-time": lambda folder: _write(folder, "bad.yaml", ONE_PAIR.replace(", duration_s: 5100", "")),
    "negative-distance": lambda folder: _write(folder, "bad.yaml", ONE_PAIR.replace("86100", "-1")),
    "listed-twice-differently": lambda folder: _write(
        folder, "bad.yaml", ONE_PAIR + ONE_PAIR.removeprefix("pairs:\n").replace("5100", "5200")
    ),
    **{
        f"latency-{name}": lambda folder, latency=latency: _write(
            folder, "bad.yaml", f"pairs: []\nlatency: {latency}\n"
        )
        for name, latency in {
            "not-a-mapping": "[1000, 60]",
            "without-the-seconds": "{answered_at_once_pairs: 1000}",
            "with-another-key": "{answered_at_once_pairs: 1000, then_each_call_s: 60, latency_ms: 5}",
            "negative-pairs": "{answered_at_once_pairs: -1, then_each_call_s: 60}",
            "fractional-pairs": "{answered_at_once_pairs: 2.5, then_each_call_s: 60}",
            "negative-seconds": "{answered_at_once_pairs: 1000, then_each_call_s: -0.5}",
            "seconds-not-a-number": "{answered_at_once_pairs: 1000, then_each_call_s: soon}",
            "seconds-a-boolean": "{answered_at_once_pairs: 1000, then_each_call_s: true}",
        }.items()
    },
}


@pytest.mark.parametrize("bad", BAD_ROAD_MAPS.values(), ids=BAD_ROAD_MAPS.keys())
def test_bad_road_map_refuses_start(tmp_path: Path, bad: object) -> None:
    path = bad(tmp_path)  # type: ignore[operator]

    with pytest.raises(InvalidRoadMapError) as refused:
        read_road_map(path)

    assert str(path) in str(refused.value)


def test_a_pair_listed_twice_with_the_same_values_is_one_pair(tmp_path: Path) -> None:
    path = _write(tmp_path, "twice.yaml", ONE_PAIR + ONE_PAIR.removeprefix("pairs:\n"))

    (row,) = MockRoutingProvider(script=read_road_map(path)).matrix([TORINO], [PIAN_DELL_ALPE])

    assert row == [CASA_MARCO_ASSIETTA]


def test_provider_id_names_the_road_map(tmp_path: Path) -> None:
    other = _write(tmp_path, "other.yaml", PLAN_RUN_4.read_text().replace("86100", "86200"))
    sha256 = hashlib.sha256(PLAN_RUN_4.read_bytes()).hexdigest()

    ids = [MockRoutingProvider(script=read_road_map(path)).provider_id for path in (PLAN_RUN_4, other)]

    assert MockRoutingProvider().provider_id == "mock:straight_line_x1.3"
    assert ids[0] == f"mock:straight_line_x1.3:script:{sha256}"
    assert len({MockRoutingProvider().provider_id, *ids}) == 3


def test_the_probe_passes_on_the_known_pair() -> None:
    result = MockRoutingProvider().probe()

    assert (result.outcome, result.reason) == ("ok", None)


def test_the_probe_of_a_scripted_road_map_passes() -> None:
    result = MockRoutingProvider(script=read_road_map(PLAN_RUN_4)).probe()

    assert (result.outcome, result.reason) == ("ok", None)


def test_a_road_map_with_the_wrong_detour_factor_refuses_the_start() -> None:
    result = MockRoutingProvider(detour_factor=1.0).probe()

    assert (result.outcome, result.reason) == ("fatal", "routing_known_pair_wrong")


class _NoZeroForIdenticalPoints(MockRoutingProvider):
    def matrix(self, sources: Sequence[Coordinate], targets: Sequence[Coordinate]) -> Sequence[Sequence[RoadMeasure]]:
        return [
            [RoadMeasure(max(c.distance_m, 1), c.duration_s) for c in row] for row in super().matrix(sources, targets)
        ]


def test_a_road_map_that_drives_between_identical_points_refuses_the_start() -> None:
    result = _NoZeroForIdenticalPoints().probe()

    assert (result.outcome, result.reason) == ("fatal", "routing_identical_points_not_zero")


class _ScriptIgnored(MockRoutingProvider):
    def matrix(self, sources: Sequence[Coordinate], targets: Sequence[Coordinate]) -> Sequence[Sequence[RoadMeasure]]:
        return MockRoutingProvider().matrix(sources, targets)


def test_a_scripted_road_map_that_does_not_answer_its_script_refuses_the_start() -> None:
    result = _ScriptIgnored(script=read_road_map(PLAN_RUN_4)).probe()

    assert (result.outcome, result.reason) == ("fatal", "routing_scripted_pair_wrong")


# ------------------------------------------------------------- the look-up latency (06-09, brought forward from 06a)
SLOW_ROAD_MAP = "detour_factor: 1.3\npairs: []\nlatency: {answered_at_once_pairs: 1, then_each_call_s: 0.2}\n"
LATENCY_UNIVERSE = {"road_map.waits", "road_map.answers"}
alpine_points = st.builds(Coordinate, st.floats(44.0, 46.5), st.floats(6.5, 8.5))
calls = st.one_of(
    st.just("probe"),
    st.tuples(st.lists(alpine_points, min_size=1, max_size=3), st.lists(alpine_points, min_size=1, max_size=3)),
)


def test_an_empty_list_of_pairs_with_a_latency_is_a_road_map_of_defaults_whose_file_names_it(tmp_path: Path) -> None:
    path = _write(tmp_path, "slow.yaml", SLOW_ROAD_MAP)

    provider = MockRoutingProvider(script=read_road_map(path))

    assert provider.probe().outcome == "ok"
    assert provider.matrix([TORINO], [SUSA]) == [[TORINO_SUSA]]
    assert provider.provider_id == f"mock:straight_line_x1.3:script:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def test_once_the_pairs_answered_at_once_are_used_up_each_further_call_waits(tmp_path: Path) -> None:
    provider = MockRoutingProvider(script=read_road_map(_write(tmp_path, "slow.yaml", SLOW_ROAD_MAP)))

    took_s = []
    for _ in range(2):
        began_s = time.monotonic()
        provider.matrix([TORINO], [SUSA])
        took_s.append(time.monotonic() - began_s)

    assert took_s[0] < 0.1, f"the first pair is answered at once: {took_s}"
    assert took_s[1] >= 0.2, f"the call after the first pair waits 0.2 s: {took_s}"


@given(
    answered_at_once=st.integers(0, 30),
    then_each_call_s=st.floats(0, 120, allow_nan=False),
    sequence=st.lists(calls, max_size=12),
)
def test_a_call_waits_iff_the_pairs_answered_before_it_reached_the_threshold_and_a_probe_never_waits(
    answered_at_once: int, then_each_call_s: float, sequence: list[Any]
) -> None:
    latency = RoadLookUpLatency(answered_at_once, then_each_call_s)
    waits: list[float] = []
    provider = MockRoutingProvider(script=RoadMapScript(1.3, {}, "sha", latency), sleep=waits.append)
    undelayed = MockRoutingProvider(script=RoadMapScript(1.3, {}, "sha"))
    answered_before = 0
    for call in sequence:
        before = {"road_map.waits": list(waits), "road_map.answers": None}
        if call == "probe":
            answer: Any = provider.probe()
            expected_answer, expected_waits = undelayed.probe(), []
        else:
            sources, targets = call
            answer = provider.matrix(sources, targets)
            expected_answer = undelayed.matrix(sources, targets)
            expected_waits = [then_each_call_s] if answered_before >= answered_at_once else []
            answered_before += len(sources) * len(targets)
        assert_state_delta(
            before,
            {"road_map.waits": list(waits), "road_map.answers": answer},
            LATENCY_UNIVERSE,
            {
                "road_map.waits": set_to(before["road_map.waits"] + expected_waits),
                "road_map.answers": set_to(expected_answer),
            },
            strict=True,
        )

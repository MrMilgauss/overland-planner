"""The polyline decoder (Valhalla's Google encoding, 6 digits of precision): a pure function, its own driving port.

Test Budget: 2 behaviors (any encoded sequence of coordinates at 6 decimals decodes back to itself; the recorded
answer of Valhalla for Torino to Susa decodes to as many points as it holds and ends where the question did) x 2 = 4;
2 used. The encoder below is the published algorithm, written apart from the decoder, as the property's oracle.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.polyline import decode_polyline6
from tests.contract.routing_port.recordings import recording

MICRO = 1_000_000
SNAP_M = 250

micro_points = st.tuples(
    st.integers(-90 * MICRO, 90 * MICRO),
    st.integers(-180 * MICRO, 180 * MICRO),
)


def _encode_number(value: int) -> str:
    value = ~(value << 1) if value < 0 else value << 1
    chunks = []
    while value >= 0x20:
        chunks.append(chr((0x20 | (value & 0x1F)) + 63))
        value >>= 5
    chunks.append(chr(value + 63))
    return "".join(chunks)


def _encode(points: list[tuple[int, int]]) -> str:
    text, previous = "", (0, 0)
    for latitude, longitude in points:
        text += _encode_number(latitude - previous[0]) + _encode_number(longitude - previous[1])
        previous = (latitude, longitude)
    return text


@given(points=st.lists(micro_points, max_size=40))
@settings(max_examples=200, deadline=None)
def test_any_encoded_sequence_decodes_back_to_its_coordinates(points: list[tuple[int, int]]) -> None:
    decoded = decode_polyline6(_encode(points))

    assert [(round(p.latitude * MICRO), round(p.longitude * MICRO)) for p in decoded] == points


def test_the_recorded_answer_for_torino_to_susa_decodes_to_its_points_between_its_ends() -> None:
    recorded = recording("route_torino_susa_4x4v1")
    shape = recorded["response"]["trip"]["legs"][0]["shape"]
    asked = recorded["request"]["locations"]
    numbers_ended = sum(1 for character in shape if ord(character) - 63 < 0x20)  # a number ends on a chunk below 32

    decoded = decode_polyline6(shape)

    assert len(decoded) == numbers_ended // 2
    assert decoded[0].great_circle_distance_m(_at(asked[0])) <= SNAP_M
    assert decoded[-1].great_circle_distance_m(_at(asked[1])) <= SNAP_M


def _at(location: dict[str, float]) -> Coordinate:
    return Coordinate(location["lat"], location["lon"])

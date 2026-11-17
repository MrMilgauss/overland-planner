"""Decoder of Valhalla's shapes: the Google polyline encoding with 6 digits of precision. Pure domain.

Each coordinate is two signed numbers (latitude, then longitude), each the difference from the previous point's, in
millionths of a degree, zigzag-folded and written in 5-bit chunks, lowest first, as characters offset by 63 (a chunk
with the 0x20 bit set is followed by another).
"""

from __future__ import annotations

from overland_planner.domain.catalog.coordinate import Coordinate

_PRECISION = 1_000_000
_OFFSET = 63
_CONTINUES = 0x20
_CHUNK_MASK = 0x1F
_CHUNK_BITS = 5


def decode_polyline6(encoded: str) -> tuple[Coordinate, ...]:
    """The coordinates of an encoded shape; a text that does not end on a whole coordinate is a `ValueError`."""
    numbers = _numbers(encoded)
    if len(numbers) % 2:
        raise ValueError("the shape ends in the middle of a coordinate")
    latitude = longitude = 0
    points = []
    for step_latitude, step_longitude in zip(numbers[0::2], numbers[1::2], strict=True):
        latitude, longitude = latitude + step_latitude, longitude + step_longitude
        points.append(Coordinate(latitude / _PRECISION, longitude / _PRECISION))
    return tuple(points)


def _numbers(encoded: str) -> list[int]:
    numbers: list[int] = []
    value = shift = 0
    for character in encoded:
        chunk = ord(character) - _OFFSET
        if not 0 <= chunk < 2 * _CONTINUES:
            raise ValueError(f"{character!r} is not a polyline character")
        value |= (chunk & _CHUNK_MASK) << shift
        shift += _CHUNK_BITS
        if not chunk & _CONTINUES:
            numbers.append(~(value >> 1) if value & 1 else value >> 1)
            value = shift = 0
    if shift:
        raise ValueError("the shape ends in the middle of a number")
    return numbers

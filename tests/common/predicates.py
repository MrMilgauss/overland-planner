"""Domain predicates for `assert_state_delta` (same `(old, new) -> bool` contract as nwave_ai.state_delta)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from nwave_ai.state_delta import Predicate


def gained(*rows: Any) -> Predicate:
    """`new` keeps every row of `old` and adds exactly `rows` (order-insensitive)."""
    wanted = set(rows)

    def _predicate(old: Iterable[Any], new: Iterable[Any]) -> bool:
        old_set, new_set = set(old or ()), set(new or ())
        return old_set <= new_set and new_set - old_set == wanted

    _predicate.__name__ = f"gained({sorted(map(repr, wanted))})"
    return _predicate


def rows_replaced(replacements: dict[Any, Any], key_index: int = 1) -> Predicate:
    """`new` equals `old` with the rows whose key (row[key_index]) is in `replacements` swapped for the new rows."""

    def _predicate(old: Iterable[Any], new: Iterable[Any]) -> bool:
        expected = {replacements.get(row[key_index], row) for row in (old or ())}
        return expected == set(new or ())

    _predicate.__name__ = f"rows_replaced({sorted(map(repr, replacements.values()))})"
    return _predicate


def _close(expected: Any, actual: Any) -> bool:
    if isinstance(expected, tuple):
        return isinstance(actual, tuple) and len(expected) == len(actual) and all(map(_close, expected, actual))
    if expected is None or actual is None:
        return expected is actual
    if not isinstance(expected, int | float):
        return bool(expected == actual)
    return math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-9)


def close_to(expected: Any) -> Any:
    """`set_to` within float rounding: the domain sums km and seconds in its own order."""

    def _predicate(_: Any, new: Any) -> bool:
        return _close(expected, new)

    _predicate.__name__ = f"close_to({expected!r})"
    return _predicate

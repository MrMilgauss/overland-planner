"""Domain predicates for `assert_state_delta` (same `(old, new) -> bool` contract as nwave_ai.state_delta)."""

from __future__ import annotations

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

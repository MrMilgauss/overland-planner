"""The pending rule of tests/conftest.py (D262): a pending scenario runs only when every slice it is tagged with is
enabled; a scenario that is not pending always runs."""

from __future__ import annotations

import pytest

from tests.conftest import still_pending


@pytest.mark.parametrize(
    ("markers", "enabled", "pending"),
    [
        ({"pending", "slice_09"}, set(), True),
        ({"pending", "slice_09"}, {"slice_09"}, False),
        ({"pending", "slice_09", "slice_08"}, {"slice_09"}, True),
        ({"pending", "slice_09", "slice_08"}, {"slice_09", "slice_08"}, False),
        ({"pending"}, {"slice_09"}, True),
        ({"slice_09"}, set(), False),
        ({"slice_09", "slice_08"}, set(), False),
    ],
)
def test_a_pending_scenario_runs_only_when_every_slice_it_names_is_enabled(
    markers: set[str], enabled: set[str], pending: bool
) -> None:
    assert still_pending(markers, enabled) is pending

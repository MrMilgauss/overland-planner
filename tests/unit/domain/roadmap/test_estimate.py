"""estimate (D305): pause = round(6 x GB), total = round(8.2 x GB + 2.5) minutes.

Test Budget: 2 behaviors (the figures, monotonic in size) x 2 = 4.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.roadmap.estimate import estimate

GB = 1_000_000_000


@pytest.mark.parametrize(
    ("gb", "total", "pause"),
    [(6.4, 55, 38), (6.6, 57, 40), (6.8, 58, 41)],  # the owner-approved screens (D305)
)
def test_the_approved_figures(gb, total, pause):
    result = estimate(round(gb * GB))
    assert (result.total_minutes, result.pause_minutes) == (total, pause)


@given(a=st.integers(0, 40 * GB), b=st.integers(0, 40 * GB))
def test_both_figures_grow_with_size(a, b):
    small, large = sorted((a, b))
    low, high = estimate(small), estimate(large)
    assert low.total_minutes <= high.total_minutes
    assert low.pause_minutes <= high.pause_minutes

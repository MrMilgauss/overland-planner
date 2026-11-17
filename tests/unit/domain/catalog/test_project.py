"""Project name rule (D151): surrounding whitespace is trimmed; a name empty after trimming is refused.

Driving port: the pure domain constructor `ProjectName(raw)` (its signature is the public interface).
Test Budget: 2 behaviors (accept + trim, refuse blank) x 2 = 4; 2 property tests used.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from overland_planner.domain.catalog.project import (
    Objective,
    OffroadSpeed,
    OffroadSpeedNotDrivableError,
    Project,
    ProjectName,
    ProjectNameRequiredError,
)
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"name.value", "refusal"}
WHITESPACE = st.text(alphabet=st.sampled_from([" ", "\t", "\n", "\r", chr(0xA0), chr(0x2003)]), max_size=12)
VISIBLE = st.text(min_size=1).filter(lambda s: s.strip() != "")


def _outcome(raw: str) -> dict[str, Any]:
    try:
        return {"name.value": ProjectName(raw).value, "refusal": None}
    except ProjectNameRequiredError as refused:
        return {"name.value": None, "refusal": str(refused)}


@given(raw=WHITESPACE)
def test_a_blank_name_is_refused_with_give_the_project_a_name(raw: str) -> None:
    before = {"name.value": None, "refusal": None}
    after = _outcome(raw)
    assert_state_delta(before, after, UNIVERSE, {"refusal": set_to("Give the project a name")}, strict=True)


@given(lead=WHITESPACE, core=VISIBLE, trail=WHITESPACE)
def test_a_name_with_a_visible_character_is_kept_without_surrounding_whitespace(
    lead: str, core: str, trail: str
) -> None:
    before = {"name.value": None, "refusal": None}
    after = _outcome(lead + core + trail)
    assert_state_delta(before, after, UNIVERSE, {"name.value": set_to(core.strip())}, strict=True)
    with pytest.raises(ProjectNameRequiredError):  # the refusal is a domain error, not a silent default
        ProjectName(lead + trail)


# --- off-road speed (slice 02, US-05 S4, FR-4.6) -------------------------------------------------------------------
# Driving port: the pure domain constructor `OffroadSpeed(kmh)` and `Project.create` (its default).
# Test Budget: 2 behaviors (any float is taken or refused, a new project drives 15 km/h) x 2 = 4; 2 used.
SPEED_UNIVERSE = {"speed.kmh", "refusal"}
REFUSAL = "Off-road speed must be more than 0 km/h"


def _speed_outcome(kmh: float) -> dict[str, Any]:
    try:
        return {"speed.kmh": OffroadSpeed(kmh).kmh, "refusal": None}
    except OffroadSpeedNotDrivableError as refused:
        return {"speed.kmh": None, "refusal": str(refused)}


@given(kmh=st.floats(allow_nan=True, allow_infinity=True, allow_subnormal=True))
@example(kmh=0.0)
@example(kmh=-0.0)
@example(kmh=5e-324)
@example(kmh=float("nan"))
@example(kmh=float("inf"))
@example(kmh=float("-inf"))
def test_a_speed_is_taken_only_when_finite_and_above_zero(kmh: float) -> None:
    before = {"speed.kmh": None, "refusal": None}
    drivable = math.isfinite(kmh) and kmh > 0
    expected = {"speed.kmh": set_to(kmh)} if drivable else {"refusal": set_to(REFUSAL)}
    assert_state_delta(before, _speed_outcome(kmh), SPEED_UNIVERSE, expected, strict=True)


@given(name=VISIBLE)
def test_a_new_project_drives_off_road_at_15_kmh(name: str) -> None:
    # FR-4.6: the default is fixed in the domain (D220 i).
    project = Project.create("p", ProjectName(name), datetime(2027, 6, 1, tzinfo=UTC))
    assert project.offroad_speed == OffroadSpeed(15)


def test_the_objectives_are_labelled_in_the_words_marco_reads() -> None:
    # bypass: the two labels are a fixed vocabulary of the product (feature text), not a rule over inputs.
    assert {objective.value: objective.label for objective in Objective} == {
        "distance": "minimise road distance",
        "time": "minimise road time",
    }

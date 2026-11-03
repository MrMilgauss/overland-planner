"""Project name rule (D151): surrounding whitespace is trimmed; a name empty after trimming is refused.

Driving port: the pure domain constructor `ProjectName(raw)` (its signature is the public interface).
Test Budget: 2 behaviors (accept + trim, refuse blank) x 2 = 4; 2 property tests used.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.catalog.project import ProjectName, ProjectNameRequiredError
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

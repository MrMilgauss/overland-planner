"""The user-facing lines of a plan run's results (D223 b, words as D220 e: no underscore).

Driving port: `run_messages(not_fully_optimised)`, a pure domain function (its signature is the interface).
Test Budget: 1 behavior (a run's flags give its lines) x 2 = 2; 1 property test used. The texts are written here as
the product shows them, not imported. Slices 06-07, 06-08 and 06-10 add the time limit, Stop and run time lines.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.planning.run_messages import run_messages
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"messages"}
SHOWN = {  # the run's not_fully_optimised code -> what Marco reads (D223 b)
    None: (),
    "optimizer_failed": ("not fully optimised (optimizer failed)",),
}


@given(code=st.sampled_from(sorted(SHOWN, key=str)))
def test_a_run_shows_the_label_of_how_its_search_ended(code: str | None) -> None:
    after = {"messages": run_messages(code)}

    assert_state_delta({"messages": ()}, after, UNIVERSE, {"messages": set_to(SHOWN[code])}, strict=True)
    assert all("_" not in text for text in after["messages"]), "labels are words, never codes (D220 e)"

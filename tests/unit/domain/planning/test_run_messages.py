"""The user-facing lines of a plan run's results and of its ended job (D223 b, words as D220 e: no underscore; D151).

Driving ports: `run_messages(not_fully_optimised, failure_reason=..., number=...)` and `job_message(failure_reason,
number)`, pure domain functions (their signatures are the interface).
Test Budget: 1 behavior (a run's flags and reason give its lines and its job's message) x 2 = 2; 1 property test used.
The texts are written here as the product shows them, not imported. Slice 06-10 adds the run time line.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.planning.run_messages import job_message, run_messages
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"messages", "job.message"}
SHOWN = {  # a ready run's not_fully_optimised code -> what Marco reads (D223 b)
    None: (),
    "optimizer_failed": ("not fully optimised (optimizer failed)",),
    "time_limit": ("not fully optimised (time limit)",),
    "stopped": ("not fully optimised (stopped)",),
}
FAILED_TEXT = {  # a Failed run's reason -> what Marco reads, N its number (D151); other reasons say nothing yet
    "timeout": "No valid route found within the time limit - plan run #{number} failed",
    "stopped": "stopped before a valid route was found",  # the feature's words (US-06b S2), with no number
}
OTHER_REASONS = ("no_valid_route_found", "optimizer_failed", "internal_invariant_violation")


@given(
    run=st.one_of(
        st.tuples(st.sampled_from(sorted(SHOWN, key=str)), st.none()),
        st.tuples(st.none(), st.sampled_from(sorted([*FAILED_TEXT, *OTHER_REASONS]))),
    ),
    number=st.integers(min_value=1, max_value=10**6),
)
def test_a_run_shows_the_label_of_how_its_search_ended_and_a_timeout_names_the_failed_run(
    run: tuple[str | None, str | None], number: int
) -> None:
    code, reason = run
    failed_text = FAILED_TEXT[reason].format(number=number) if reason in FAILED_TEXT else None

    after = {
        "messages": run_messages(code, failure_reason=reason, number=number),
        "job.message": job_message(reason, number),
    }

    expected_lines = SHOWN[code] + ((failed_text,) if failed_text is not None else ())
    assert_state_delta(
        {"messages": (), "job.message": None},
        after,
        UNIVERSE,
        {"messages": set_to(expected_lines), "job.message": set_to(failed_text)},
        strict=True,
    )
    assert all("_" not in text for text in after["messages"]), "labels are words, never codes (D220 e)"

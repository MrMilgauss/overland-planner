"""The user-facing lines of a plan run's results, of its ended job and of a Calculate (D223 b, D220 e; D151; D146).

Driving ports: `run_messages(not_fully_optimised, failure_reason=..., number=..., items_planned=..., run_time_ms=...,
reused_from=...)`, `job_message(failure_reason, number)`, `run_time_text(ms)` and `project_notices(items)`, pure domain
functions (their signatures are the interface).
Test Budget: 3 behaviors (a run's stored facts give its lines and its job's message; a run time reads in the binding's
pattern at its precision; a project above 60 Included items gets the large-project notice) x 2 = 6; 3 property tests
used. The texts are written here as the product shows them, not imported.
"""

from __future__ import annotations

import re

from hypothesis import example, given
from hypothesis import strategies as st

from overland_planner.domain.planning.run_messages import job_message, project_notices, run_messages, run_time_text
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
RUN_TIME = re.compile(r" (?:(?P<h>\d+) h )?(?:(?P<min>\d+) min )?(?P<s>\d+(?:\.\d+)?) s")  # the binding's pattern
KNOWN = {2_400: "2.4 s", 41_000: "41 s", 161_000: "2 min 41 s", 3_725_000: "1 h 02 min 05 s"}  # the roadmap's
NOTICE = "Large project - calculation may take longer than 3 minutes"
MS = st.integers(min_value=0, max_value=30 * 3_600_000)


@given(
    run=st.one_of(
        st.tuples(st.sampled_from(sorted(SHOWN, key=str)), st.none()),
        st.tuples(st.none(), st.sampled_from(sorted([*FAILED_TEXT, *OTHER_REASONS]))),
    ),
    number=st.integers(min_value=1, max_value=10**6),
    items=st.integers(min_value=0, max_value=200),
    run_time_ms=st.none() | MS,
    reused_from=st.none() | st.integers(min_value=1, max_value=10**6),
)
def test_a_run_shows_its_run_time_its_label_its_source_and_a_timeout_names_the_failed_run(
    run: tuple[str | None, str | None], number: int, items: int, run_time_ms: int | None, reused_from: int | None
) -> None:
    code, reason = run
    failed_text = FAILED_TEXT[reason].format(number=number) if reason in FAILED_TEXT else None

    after = {
        "messages": run_messages(
            code,
            failure_reason=reason,
            number=number,
            items_planned=items,
            run_time_ms=run_time_ms,
            reused_from=reused_from,
        ),
        "job.message": job_message(reason, number),
    }

    ready = reason is None
    planned = (f"Planned {items} items in {run_time_text(run_time_ms)}",) if ready and run_time_ms is not None else ()
    reused = (f"Reused the identical plan of run #{reused_from}",) if ready and reused_from is not None else ()
    expected_lines = planned + SHOWN[code] + reused + ((failed_text,) if failed_text is not None else ())
    assert_state_delta(
        {"messages": (), "job.message": None},
        after,
        UNIVERSE,
        {"messages": set_to(expected_lines), "job.message": set_to(failed_text)},
        strict=True,
    )
    assert all("_" not in text for text in after["messages"]), "labels are words, never codes (D220 e)"


@given(ms=MS)
@example(ms=2_400)
@example(ms=41_000)
@example(ms=161_000)
@example(ms=3_725_000)
@example(ms=9_949)  # the last tenth below 10 s
@example(ms=9_950)  # rounds to 10 s: whole seconds from there on
@example(ms=59_500)  # rounds to a whole minute
def test_a_run_time_reads_in_the_binding_pattern_and_back_to_its_seconds_at_its_precision(ms: int) -> None:
    text = run_time_text(ms)

    shown = RUN_TIME.fullmatch(f" {text}")
    assert shown is not None, f"{text!r} is not a run time"
    hours, minutes = int(shown["h"] or 0), int(shown["min"] or 0)
    seconds = float(shown["s"])
    read_back = hours * 3600 + minutes * 60 + seconds
    tenths = "." in shown["s"]
    assert abs(read_back - ms / 1000) <= (0.05 if tenths else 0.5) + 1e-9, f"{text!r} for {ms} ms"
    assert tenths == (read_back < 10), f"one decimal below 10 s only: {text!r}"
    assert seconds < 60 and minutes < 60, f"{text!r} carries over"
    assert (shown["h"] is not None) == (read_back >= 3600), f"hours only from 1 h: {text!r}"
    assert (shown["min"] is not None) == (read_back >= 60), f"minutes only from 1 min: {text!r}"
    if shown["min"] is not None:
        assert re.fullmatch(r"\d{2}", shown["s"]) and (shown["h"] is None or len(shown["min"]) == 2), text
    assert ms not in KNOWN or text == KNOWN[ms], f"{ms} ms reads {text!r}, not {KNOWN[ms]!r}"


@given(items=st.integers(min_value=0, max_value=500))
@example(items=60)
@example(items=61)
def test_a_project_above_sixty_included_items_gets_the_large_project_notice_and_no_upper_bound(items: int) -> None:
    assert project_notices(items) == ((NOTICE,) if items > 60 else ())

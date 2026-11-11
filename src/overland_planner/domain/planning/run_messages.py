"""The user-facing lines of a plan run's results, its ended job and a Calculate (D223 b, D220 e: words, never codes).

Every text a run shows is composed here, on read, from the facts stored with it: no wording is stored. A ready run
written since 06-10 says how many Included items it planned and how long planning took, from the work's start to the
run stored (`run_time_ms`): one decimal below 10 s, whole seconds from there on ("2.4 s", "41 s", "2 min 41 s",
"1 h 02 min 05 s"). A ready run that is not fully optimised names why in words; the code stays in its
`not_fully_optimised`. A memo hit names the run it reused by number (ADR-014 section 5). A run that failed on the
feasibility limit names itself by number (D151); the reason code stays `timeout` (ADR-015). A run stopped before a valid
route was found says so in the feature's words (US-06b), its code `stopped`. A run that failed as `unreachable` names
each item no order can connect, one line per item, with the run's number (US-08 S1); the job's ending message says the
same, the lines joined. A project of more than 60 Included items other than its anchors is planned with a notice, never
refused (D146).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

NotFullyOptimised = Literal["optimizer_failed", "time_limit", "stopped"]

LARGE_PROJECT_ITEMS = 60
LARGE_PROJECT_NOTICE = "Large project - calculation may take longer than 3 minutes"
_LABELS: dict[str, str] = {
    "optimizer_failed": "not fully optimised (optimizer failed)",
    "time_limit": "not fully optimised (time limit)",
    "stopped": "not fully optimised (stopped)",
}
_FAILED: dict[str, str] = {
    "timeout": "No valid route found within the time limit - plan run #{number} failed",
    "stopped": "stopped before a valid route was found",
}
UNREACHABLE = "unreachable"
_UNREACHABLE = "Plan run #{number} failed: '{item}' cannot be connected to any other stop at any confidence level"
_MS_PER_TENTH = 100
_MS_PER_SECOND = 1000
_TENTHS_SHOWN_BELOW = 100  # 10 s
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600


def run_time_text(run_time_ms: int) -> str:
    """The run time as the results show it, rounded half up at its precision."""
    tenths = (run_time_ms + _MS_PER_TENTH // 2) // _MS_PER_TENTH
    if tenths < _TENTHS_SHOWN_BELOW:
        return f"{tenths // 10}.{tenths % 10} s"
    seconds = (run_time_ms + _MS_PER_SECOND // 2) // _MS_PER_SECOND
    hours, rest = divmod(seconds, _SECONDS_PER_HOUR)
    minutes, seconds = divmod(rest, _SECONDS_PER_MINUTE)
    if hours:
        return f"{hours} h {minutes:02d} min {seconds:02d} s"
    if minutes:
        return f"{minutes} min {seconds:02d} s"
    return f"{seconds} s"


def project_notices(items: int) -> tuple[str, ...]:
    """What a Calculate of a project with `items` Included non-anchor items says first: no upper bound (D146)."""
    return (LARGE_PROJECT_NOTICE,) if items > LARGE_PROJECT_ITEMS else ()


def run_messages(
    not_fully_optimised: str | None,
    *,
    failure_reason: str | None = None,
    number: int | None = None,
    items_planned: int | None = None,
    run_time_ms: int | None = None,
    reused_from: int | None = None,
    items: Sequence[str] = (),
) -> tuple[str, ...]:
    """The lines a run shows, in order: its run time, its label, the run it reused, and its failure in words.

    A run stored before 06-10 has no run time (`None`), so no run time line."""
    lines: list[str] = []
    if failure_reason is None and run_time_ms is not None and items_planned is not None:
        lines.append(f"Planned {items_planned} items in {run_time_text(run_time_ms)}")
    if not_fully_optimised is not None:
        lines.append(_LABELS[not_fully_optimised])
    if failure_reason is None and reused_from is not None:
        lines.append(f"Reused the identical plan of run #{reused_from}")
    return (*lines, *_failure_lines(failure_reason, number, items))


def job_message(failure_reason: str | None, number: int | None, items: Sequence[str] = ()) -> str | None:
    """What the ended job of a Failed run says, naming the run's number; `None` for a reason with no words yet."""
    return "; ".join(_failure_lines(failure_reason, number, items)) or None


def _failure_lines(failure_reason: str | None, number: int | None, items: Sequence[str]) -> tuple[str, ...]:
    if failure_reason == UNREACHABLE and number is not None:
        return tuple(_UNREACHABLE.format(number=number, item=item) for item in items)
    if failure_reason not in _FAILED or number is None:
        return ()
    return (_FAILED[failure_reason].format(number=number),)

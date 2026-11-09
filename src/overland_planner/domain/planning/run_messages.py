"""The user-facing lines of a plan run's results and of its ended job (D223 b, worded as D220 e: words, never codes).

A ready run that is not fully optimised names why in words; the code stays in its `not_fully_optimised`. A run that
failed on the feasibility limit names itself by number (D151); the reason code stays `timeout` (ADR-015). A run stopped
before a valid route was found says so in the feature's words (US-06b), its code `stopped`. Slice 06-10 adds the run
time line here.
"""

from __future__ import annotations

from typing import Literal

NotFullyOptimised = Literal["optimizer_failed", "time_limit", "stopped"]

_LABELS: dict[str, str] = {
    "optimizer_failed": "not fully optimised (optimizer failed)",
    "time_limit": "not fully optimised (time limit)",
    "stopped": "not fully optimised (stopped)",
}
_FAILED: dict[str, str] = {
    "timeout": "No valid route found within the time limit - plan run #{number} failed",
    "stopped": "stopped before a valid route was found",
}


def run_messages(
    not_fully_optimised: str | None, *, failure_reason: str | None = None, number: int | None = None
) -> tuple[str, ...]:
    """The lines a run shows: its label when its search did not end on the budget, and its failure in words."""
    label = () if not_fully_optimised is None else (_LABELS[not_fully_optimised],)
    failed = job_message(failure_reason, number)
    return label if failed is None else (*label, failed)


def job_message(failure_reason: str | None, number: int | None) -> str | None:
    """What the ended job of a Failed run says, naming the run's number; `None` for a reason with no words yet."""
    if failure_reason not in _FAILED or number is None:
        return None
    return _FAILED[failure_reason].format(number=number)

"""The user-facing lines of a plan run's results (D223 b, worded as D220 e: words, never codes). Pure domain.

A ready run that is not fully optimised names why in words; the code stays in its `not_fully_optimised`. Slices 06-07,
06-08 and 06-10 add the time limit and Stop labels and the run time line here.
"""

from __future__ import annotations

from typing import Literal

NotFullyOptimised = Literal["optimizer_failed"]  # time_limit (06-07) and stopped (06-08) next

_LABELS: dict[str, str] = {
    "optimizer_failed": "not fully optimised (optimizer failed)",
}


def run_messages(not_fully_optimised: str | None) -> tuple[str, ...]:
    """The lines a run shows: its label when its search did not end on the budget, none otherwise."""
    if not_fully_optimised is None:
        return ()
    return (_LABELS[not_fully_optimised],)

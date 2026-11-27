"""The owner's words for a rebuild's result (D303, D304, D314): bash carries a code and numbers, the planner owns every
sentence. A code this table does not know reads as a generic failure; free text from the helper is never shown."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

_AGAIN = "press Rebuild road map again"
_LATER = f"{_AGAIN} in a while"
_CHECK = f"have a look at the Pi, then {_AGAIN}"

# code -> (what stopped it, what to do about it); sentences with numbers are built in `_reason`.
_TABLE: dict[str, tuple[str, str]] = {
    "locked": ("the Pi was busy with another job for half an hour", _LATER),
    "date": ("a road map was already built today", f"{_AGAIN} tomorrow"),
    "disk": ("the Pi does not have enough free disk", "free some space and " + _AGAIN),
    "memory": ("the Pi does not have enough memory", f"free some memory on the Pi and {_AGAIN}"),
    "routing_status": ("the road service of the Pi did not answer", _CHECK),
    "download": ("a download failed", _LATER),
    "region_missing": ("the border file of a region was not found", f"change the regions and {_AGAIN}"),
    "merge": ("the regions could not be merged", _CHECK),
    "build": ("the map could not be built", _CHECK),
    "build_oom": ("the Pi ran out of memory building the map", f"free some memory on the Pi and {_AGAIN}"),
    "overrides": ("the road rules could not be applied", _CHECK),
    "promote": ("the new map could not be put in place", _CHECK),
    "switch": ("the new map did not start", _CHECK),
    "bad_request": ("the planned change could not be read by the Pi", f"plan the change again and {_AGAIN}"),
    "interrupted": ("the Pi lost power or restarted during the rebuild", _AGAIN),
}
FAILURE_CODES = tuple(_TABLE)
_GENERIC = ("something went wrong", _CHECK)


def failure_message(
    code: str | None,
    *,
    map_date: datetime | None,
    kept: bool,
    free_gb: int | None = None,
    need_gb: int | None = None,
    have_gb: int | None = None,
) -> str:
    """The plain sentence for a failed rebuild; the previous road map is back, and the change stays when `kept`."""
    reason, action = _TABLE.get(code or "", _GENERIC)
    if code == "disk" and free_gb is not None and need_gb is not None:
        reason = f"the Pi has {free_gb} GB of free disk and needs {need_gb} GB"
    elif code == "memory" and have_gb is not None:
        reason = f"the Pi has only {have_gb} GB of memory, too little to rebuild the map"
    back = "The previous road map is back" + ("" if map_date is None else f" (map data {_day(map_date)})")
    kept_words = f" Your change is kept: {action}." if kept else ""
    return f"The rebuild didn't finish: {reason}. {back}; nothing is lost.{kept_words}"


def success_message(
    *,
    finished_at: datetime,
    added: Sequence[str],
    removed: Sequence[str],
    region_count: int,
    map_date: datetime | None,
) -> str:
    """ "Road map rebuilt on 27 November at 02:56. Utah added; 9 regions, map data 27 November 2026.\""""
    changes = ", ".join(part for part in (_names(added, "added"), _names(removed, "removed")) if part)
    held = f"{region_count} regions" + ("" if map_date is None else f", map data {_day(map_date)}")
    return f"Road map rebuilt on {finished_at.day} {finished_at:%B} at {finished_at:%H:%M}. " + (
        f"{changes}; {held}." if changes else f"{held}."
    )


def _names(names: Sequence[str], verb: str) -> str:
    if not names:
        return ""
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{listed} {verb}"


def _day(moment: datetime) -> str:
    return f"{moment.day} {moment:%B %Y}"

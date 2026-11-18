"""The header a plan run's results show to name its road map (ADR-013 Amendment 4, D250). Pure: no I/O.

Built from what the run stored: `valhalla:<version>:<tileset_last_modified epoch>` and profile `4x4.v1` read
"Provider: Valhalla (map data 2026-11-01) / profile: 4x4" (the UTC date of the map data); the offline road map,
`mock:straight_line_x<factor>` with an optional `:script:<hash>`, and profile `mock.v1` read "Provider: offline
estimate (straight line x 1.3) / profile: estimate". A run stored without a profile shows the provider part only, and a
road map this planner does not know is shown as stored.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

_VALHALLA = re.compile(r"valhalla:[^:]+:(?P<epoch>\d+)")
_OFFLINE = re.compile(r"mock:straight_line_x(?P<factor>[^:]+)(?::script:.*)?")
_LAST_DATED_EPOCH = 253_402_300_799  # 9999-12-31T23:59:59Z; beyond it (milliseconds?) the id is shown as stored
_PROFILE_VERSION = re.compile(r"\.v\d+$")
_OFFLINE_ID = "mock"
_PROFILE_WORDS = {"mock": "estimate"}


def provider_header(provider_id: str, profile: str | None) -> str:
    header = f"Provider: {_provider_words(provider_id)}"
    return header if profile is None else f"{header} / profile: {_profile_words(profile)}"


def is_estimate(provider_id: str) -> bool:
    """True for the offline road map in every form it was stored: `mock` and every id starting `mock:` (D275)."""
    return provider_id == _OFFLINE_ID or provider_id.startswith(f"{_OFFLINE_ID}:")


def _provider_words(provider_id: str) -> str:
    valhalla = _VALHALLA.fullmatch(provider_id)
    if valhalla is not None and int(valhalla["epoch"]) <= _LAST_DATED_EPOCH:
        return f"Valhalla (map data {_utc_date(int(valhalla['epoch']))})"
    offline = _OFFLINE.fullmatch(provider_id)
    if offline is not None and _is_number(offline["factor"]):
        return f"offline estimate (straight line x {offline['factor']})"
    return provider_id


def _utc_date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).date().isoformat()


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _profile_words(profile: str) -> str:
    name = _PROFILE_VERSION.sub("", profile)
    return _PROFILE_WORDS.get(name, name)

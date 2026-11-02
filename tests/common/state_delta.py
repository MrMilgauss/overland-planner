"""Project-local state-delta port (Mandate 8), Python binding.

Thin re-export of the canonical ``nwave_ai.state_delta`` package (dev dependency). Every state-mutating
acceptance step at layers 1-3 asserts through :func:`assert_state_delta` with a universe of port-exposed
observable names (what the planner shows through its driving ports), never internal fields.
"""

from nwave_ai.state_delta import (
    assert_state_delta,
    appended_with,
    containing,
    idempotent_after,
    legacy_healed,
    normalized_to,
    prepended_with,
    set_to,
    unchanged,
)

__all__ = [
    "assert_state_delta",
    "appended_with",
    "containing",
    "idempotent_after",
    "legacy_healed",
    "normalized_to",
    "prepended_with",
    "set_to",
    "unchanged",
]

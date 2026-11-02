"""Probeable port contract (ADR-011): every driven port can prove it works before traffic is served.

RED scaffold (created by DISTILL). The data shape below is the minimum the acceptance fakes need;
DELIVER may extend it (keep the outcome names: they mirror ADR-011's fatal / degraded / not_applicable).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

__SCAFFOLD__ = True

ProbeOutcome = Literal["ok", "degraded", "fatal", "not_applicable"]


@dataclass(frozen=True)
class ProbeResult:
    outcome: ProbeOutcome
    reason: str | None = None


class Probeable(Protocol):
    def probe(self) -> ProbeResult: ...

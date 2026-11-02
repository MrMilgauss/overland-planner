"""Probeable port contract (ADR-011 + Amendment 1): every driven port proves it works before traffic is served.

Every driven port Protocol extends `Probeable`; the composition root registers adapters in a typed registry
(`bootstrap/registry.py`), so mypy strict rejects an adapter without a `probe()`.

Outcomes (ADR-011 and its amendments):
- `ok`: works.
- `not_applicable`: the check does not apply on this host (e.g. no mount table on macOS, DV-7); healthy.
- `degraded-healthy`: serve, stay healthy, refuse the affected jobs (e.g. routing engine still loading tiles).
- `degraded-unhealthy`: serve, `/healthz` 503 with the reason, home-page banner (e.g. non-persistent `DATA_DIR`).
- `fatal`: refuse to start (`health.startup.refused`, exit non-zero; enforced from 02-01).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ProbeOutcome = Literal["ok", "not_applicable", "degraded-healthy", "degraded-unhealthy", "fatal"]


@dataclass(frozen=True)
class ProbeResult:
    outcome: ProbeOutcome
    reason: str | None = None


class Probeable(Protocol):
    def probe(self) -> ProbeResult: ...

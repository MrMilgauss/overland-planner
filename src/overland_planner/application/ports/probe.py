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

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

ProbeOutcome = Literal["ok", "not_applicable", "degraded-healthy", "degraded-unhealthy", "fatal"]


@dataclass(frozen=True)
class ProbeResult:
    outcome: ProbeOutcome
    reason: str | None = None


class Probeable(Protocol):
    def probe(self) -> ProbeResult: ...


@dataclass(frozen=True)
class ProbeCheck:
    """One step of a probe that is fatal when it fails; `reason` names the step."""

    reason: str
    passes: Callable[[], bool]


def first_failure(checks: Iterable[ProbeCheck], *, failing_errors: tuple[type[Exception], ...]) -> ProbeResult:
    """Run the checks in order and stop at the first one that fails: fatal with its reason, else ok.

    A check that raises one of `failing_errors` has failed; any other error propagates.
    """
    for check in checks:
        try:
            passed = check.passes()
        except failing_errors:
            passed = False
        if not passed:
            return ProbeResult(outcome="fatal", reason=check.reason)
    return ProbeResult(outcome="ok")

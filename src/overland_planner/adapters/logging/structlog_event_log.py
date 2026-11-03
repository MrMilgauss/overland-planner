"""`EventLog` adapter: one JSON object per stdout line (brief §12), timestamped by the `Clock` port in UTC.

Common fields on every line (kpi-contracts.yaml `common_event_fields`): `ts`, `level`, `event`, `app_version`.
No level filter yet: `app.started` must appear exactly once per start whatever LOG_LEVEL says (D110/D155).
Secrets (brief §12): a processor replaces the value of any `password` / `authorization` field, at any depth, and every
occurrence of the configured shared password inside any text, with `[redacted]`.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, MutableMapping
from datetime import UTC
from typing import Any

import structlog

from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.probe import ProbeResult

REDACTED = "[redacted]"
_SECRET_KEYS = frozenset({"password", "authorization"})


class _Redactor:
    """Replaces the value of any secret-named field, at any depth, and every occurrence of the shared password."""

    def __init__(self, secret: str | None) -> None:
        self._secret = secret or None

    def __call__(self, _logger: Any, _method: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        return {key: self._scrub(key, value) for key, value in event_dict.items()}

    def _scrub(self, key: object, value: Any) -> Any:
        if isinstance(key, str) and key.lower() in _SECRET_KEYS:
            return REDACTED
        if isinstance(value, str):
            return value.replace(self._secret, REDACTED) if self._secret else value
        if isinstance(value, Mapping):
            return {k: self._scrub(k, v) for k, v in value.items()}
        if isinstance(value, list | tuple | set | frozenset):
            return [self._scrub(None, item) for item in value]
        return value


class StructlogEventLog:
    def __init__(self, clock: Clock, *, app_version: str, secret: str | None = None) -> None:
        self._clock = clock
        self._logger = structlog.wrap_logger(
            structlog.PrintLogger(sys.stdout),
            processors=[
                structlog.processors.add_log_level,
                self._add_timestamp,
                _Redactor(secret),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.NOTSET),
            cache_logger_on_first_use=False,
        ).bind(app_version=app_version)

    def _add_timestamp(
        self, _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        event_dict["ts"] = self._clock.now().astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return event_dict

    def info(self, event: str, **fields: object) -> None:
        self._logger.info(event, **fields)

    def warning(self, event: str, **fields: object) -> None:
        self._logger.warning(event, **fields)

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

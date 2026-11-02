"""`EventLog` adapter: one JSON object per stdout line (brief §12), timestamped by the `Clock` port in UTC.

Common fields on every line (kpi-contracts.yaml `common_event_fields`): `ts`, `level`, `event`, `app_version`.
No level filter yet: `app.started` must appear exactly once per start whatever LOG_LEVEL says (D110/D155).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from datetime import UTC
from typing import Any

import structlog

from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.probe import ProbeResult


class StructlogEventLog:
    def __init__(self, clock: Clock, *, app_version: str) -> None:
        self._clock = clock
        self._logger = structlog.wrap_logger(
            structlog.PrintLogger(sys.stdout),
            processors=[
                structlog.processors.add_log_level,
                self._add_timestamp,
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

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

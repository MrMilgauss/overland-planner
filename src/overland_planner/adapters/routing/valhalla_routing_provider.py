"""RoutingProvider on a self-hosted Valhalla (ADR-013 sections 2 to 6 and Amendment 4).

Identity: `provider_id` is `valhalla:<version>:<tileset_last_modified>` from `/status`, read on first use and again
after every probe; `profile` is `4x4.v1`, the `auto` costing with the options below.

Matrix: a question posts `/sources_to_targets` with each place carrying `search_cutoff = snap_m`. The engine answers
`distance` in km and `time` in whole seconds per cell; a null cell is no road at any level (`None`). The distance reads
to whole metres, and distinct points are never less than 1 m and 1 s apart. A question above `max_matrix_pairs` cells
is split into rectangular sub-batches of at most that many cells (`floor(max / sources)` targets per call; the sources
are split too when one column alone exceeds the limit); at most `concurrency` calls are in flight at a time, through one
semaphore shared by every call of the adapter (D133).

Any answer other than 200 is a `ProviderRejected` naming the engine's error code; the retries, the other typed errors
and the full probe are step 09-03. `transport` is the httpx transport seam of the tests and of the composition root.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.routing_provider import (
    ProviderRejected,
    ProviderUnavailable,
    RoadCell,
    RoutingObserver,
)
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import RoadMeasure

PROFILE = "4x4.v1"
COSTING = "auto"
COSTING_OPTIONS: dict[str, dict[str, Any]] = {
    "auto": {
        "use_tracks": 1.0,
        "exclude_unpaved": False,
        "use_highways": 0.5,
        "use_tolls": 0.5,
        "use_ferry": 0.5,
        "country_crossing_cost": 0,
        "country_crossing_penalty": 0,
        "ignore_oneways": False,
    }
}
_METRES_PER_KM = 1000
_CONNECT_TIMEOUT_S = 2
_MATRIX_READ_TIMEOUT_S = 120
_OTHER_READ_TIMEOUT_S = 30
_Cells = list[list[RoadCell]]


class ValhallaRoutingProvider:
    def __init__(
        self,
        base_url: str,
        *,
        expected_version: str,
        max_matrix_pairs: int,
        concurrency: int,
        snap_m: int,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._expected_version = expected_version
        self._max_pairs = max_matrix_pairs
        self._snap_m = snap_m
        self._sleep = sleep  # waits between retries (step 09-03)
        self._in_flight = threading.BoundedSemaphore(concurrency)
        self._concurrency = concurrency
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=httpx.Timeout(_OTHER_READ_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S),
        )
        self._identity: str | None = None
        self._identity_lock = threading.Lock()

    @property
    def provider_id(self) -> str:
        with self._identity_lock:
            if self._identity is None:
                self._identity = self._read_identity()
            return self._identity

    @property
    def profile(self) -> str:
        return PROFILE

    def probe(self) -> ProbeResult:
        try:
            with self._identity_lock:
                self._identity = self._read_identity()
        except (ProviderUnavailable, httpx.HTTPError) as failure:
            return ProbeResult(outcome="fatal", reason=f"the routing engine is not the expected one: {failure}")
        return ProbeResult(outcome="ok")

    def matrix(
        self, sources: Sequence[Coordinate], targets: Sequence[Coordinate], observer: RoutingObserver | None = None
    ) -> Sequence[Sequence[RoadCell]]:
        step_sources = min(len(sources), self._max_pairs)
        step_targets = self._max_pairs // step_sources
        batches = [
            (row, column, sources[row : row + step_sources], targets[column : column + step_targets])
            for row in range(0, len(sources), step_sources)
            for column in range(0, len(targets), step_targets)
        ]
        answers: _Cells = [[None] * len(targets) for _ in sources]
        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            for row, column, cells in pool.map(self._ask, batches):
                for offset, answered in enumerate(cells):
                    answers[row + offset][column : column + len(answered)] = answered
        return answers

    def _read_identity(self) -> str:
        status = self._client.get("/status").json()
        if status.get("version") != self._expected_version:
            raise ProviderUnavailable(
                f"the routing engine is Valhalla {status.get('version')}, not {self._expected_version}"
            )
        return f"valhalla:{status['version']}:{status['tileset_last_modified']}"

    def _ask(self, batch: tuple[int, int, Sequence[Coordinate], Sequence[Coordinate]]) -> tuple[int, int, _Cells]:
        row, column, sources, targets = batch
        question = {
            "sources": [self._place(place) for place in sources],
            "targets": [self._place(place) for place in targets],
            "costing": COSTING,
            "costing_options": COSTING_OPTIONS,
        }
        timeout = httpx.Timeout(_MATRIX_READ_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S)
        with self._in_flight:
            answer = self._client.post("/sources_to_targets", json=question, timeout=timeout)
        if answer.status_code != httpx.codes.OK:
            raise ProviderRejected(_refusal(answer))
        grid = answer.json()["sources_to_targets"]
        return (
            row,
            column,
            [
                [_read_cell(cell, source, target) for cell, target in zip(cells, targets, strict=True)]
                for cells, source in zip(grid, sources, strict=True)
            ],
        )

    def _place(self, place: Coordinate) -> dict[str, float | int]:
        return {"lat": place.latitude, "lon": place.longitude, "search_cutoff": self._snap_m}


def _read_cell(cell: dict[str, Any], source: Coordinate, target: Coordinate) -> RoadCell:
    if cell["time"] is None or cell["distance"] is None:
        return None
    metres, seconds = round(cell["distance"] * _METRES_PER_KM), round(cell["time"])
    if source == target:
        return RoadMeasure(distance_m=metres, duration_s=seconds)
    return RoadMeasure(distance_m=max(1, metres), duration_s=max(1, seconds))


def _refusal(answer: httpx.Response) -> str:
    try:
        body = answer.json()
        return f"the routing engine refused the question: error {body['error_code']}: {body['error']}"
    except (ValueError, KeyError, TypeError):
        return f"the routing engine refused the question: HTTP {answer.status_code}"

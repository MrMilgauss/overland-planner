"""RoutingProvider on a self-hosted Valhalla (ADR-013 sections 2 to 6 and Amendment 4).

Identity: `provider_id` is `valhalla:<version>:<tileset_last_modified>` from `/status`, read on first use and again
after every probe; `profile` is `4x4.v1`, the `auto` costing with the options below.

Matrix: a question posts `/sources_to_targets` with each place carrying `search_cutoff = snap_m`. The engine answers
`distance` in km and `time` in whole seconds per cell; a null cell is no road at any level (`None`). The distance reads
to whole metres, and distinct points are never less than 1 m and 1 s apart. A question above `max_matrix_pairs` cells
is split into rectangular sub-batches of at most that many cells (`floor(max / sources)` targets per call; the sources
are split too when one column alone exceeds the limit); at most `concurrency` calls are in flight at a time, through one
semaphore shared by every call of the adapter (D133).

Failures: a 5xx, a connect error or a timeout is made again after 0.5, 1 and 2 s (plus jitter; `sleep` and `jitter`
are injected) and each retry tells the observer; what outlives them is `ProviderUnavailable` (5xx) or
`ProviderUnreachable`.
A 4xx is never retried: it is a `ProviderRejected` naming the engine's error code. Error 170 fails the whole call: the
batch's places are located (verbose, same cutoff and costing), the call is asked again without those with no edge and
their cells answer `OffNetwork`; nothing is remembered beyond that `matrix` call. The probe reads `/status` and the 2x2
matrix of Torino and Susa once each and is never fatal. `transport` is the httpx transport seam of the tests and of the
composition root.
"""

from __future__ import annotations

import random
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
    ProviderUnreachable,
    RoadCell,
    RoutingObserver,
    RoutingProviderError,
)
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.routing.road_leg import OffNetwork, RoadMeasure

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
_UNCONNECTED_REGIONS = 170
_BACKOFF_S = (0.5, 1.0, 2.0)
_PROBE_PLACES = [Coordinate(45.0703, 7.6869), Coordinate(45.1370, 7.0500)]  # Torino, Susa
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
        jitter: Callable[[], float] = lambda: random.uniform(0.0, 0.25),  # noqa: S311 - jitter, not a secret,
    ) -> None:
        self._expected_version = expected_version
        self._max_pairs = max_matrix_pairs
        self._snap_m = snap_m
        self._sleep = sleep
        self._jitter = jitter
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
        """`/status`, then the 2x2 matrix of Torino and Susa: one attempt each, never fatal, never tells an observer."""
        try:
            found, tileset = self._read_status(retry=False)
            with self._identity_lock:
                self._identity = f"valhalla:{found}:{tileset}" if found == self._expected_version else None
            if found != self._expected_version:
                return _degraded(f"routing_engine_version_mismatch: found {found}, expected {self._expected_version}")
            grid = self._post_matrix(_PROBE_PLACES, _PROBE_PLACES, None, retry=False)
        except ProviderUnreachable:
            return _degraded("routing_engine_unreachable")
        except RoutingProviderError:
            return _degraded("routing_engine_not_ready")
        off_diagonal = (grid[0][1], grid[1][0])
        if any(not _positive(cell["distance"]) or not _positive(cell["time"]) for cell in off_diagonal):
            return _degraded("routing_engine_not_ready")
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
            for row, column, cells in pool.map(lambda batch: self._ask(batch, observer), batches):
                for offset, answered in enumerate(cells):
                    answers[row + offset][column : column + len(answered)] = answered
        return answers

    def _read_identity(self) -> str:
        found, tileset = self._read_status(retry=True)
        if found != self._expected_version:
            raise ProviderUnavailable(f"the routing engine is Valhalla {found}, not {self._expected_version}")
        return f"valhalla:{found}:{tileset}"

    def _read_status(self, *, retry: bool) -> tuple[str, Any]:
        answer = self._call("GET", "/status", None, retry=retry)
        if answer.status_code != httpx.codes.OK:
            raise ProviderUnavailable(f"the routing engine's status answered HTTP {answer.status_code}")
        try:
            status = answer.json()
            return str(status["version"]), status.get("tileset_last_modified")
        except (ValueError, KeyError, TypeError, AttributeError) as unreadable:
            raise ProviderUnavailable("the routing engine's status cannot be read") from unreadable

    def _call(
        self, method: str, path: str, observer: RoutingObserver | None, *, retry: bool = True, **options: Any
    ) -> httpx.Response:
        """One call, made again on a 5xx, a connect error or a timeout (never on a 4xx) after each wait of the
        backoff; a failure that outlives the retries is the typed error of its kind."""
        outcome = self._attempt(method, path, options)
        for wait in _BACKOFF_S if retry else ():
            if isinstance(outcome, httpx.Response):
                return outcome
            self._sleep(wait + self._jitter())
            if observer is not None:
                observer.retried()
            outcome = self._attempt(method, path, options)
        if isinstance(outcome, httpx.Response):
            return outcome
        raise outcome

    def _attempt(self, method: str, path: str, options: dict[str, Any]) -> httpx.Response | RoutingProviderError:
        try:
            with self._in_flight:
                answer = self._client.request(method, path, **options)
        except httpx.TransportError as failure:
            return ProviderUnreachable(f"the routing engine cannot be reached: {failure!r}")
        if answer.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            return ProviderUnavailable(f"the routing engine failed: HTTP {answer.status_code}")
        return answer

    def _question(self, sources: Sequence[Coordinate], targets: Sequence[Coordinate]) -> dict[str, Any]:
        return {
            "sources": [self._place(place) for place in sources],
            "targets": [self._place(place) for place in targets],
            "costing": COSTING,
            "costing_options": COSTING_OPTIONS,
        }

    def _post_matrix(
        self,
        sources: Sequence[Coordinate],
        targets: Sequence[Coordinate],
        observer: RoutingObserver | None,
        *,
        retry: bool = True,
    ) -> list[list[dict[str, Any]]]:
        timeout = httpx.Timeout(_MATRIX_READ_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S)
        answer = self._call(
            "POST", "/sources_to_targets", observer, retry=retry, json=self._question(sources, targets), timeout=timeout
        )
        if answer.status_code != httpx.codes.OK:
            raise _refusal(answer)
        try:
            grid: list[list[dict[str, Any]]] = answer.json()["sources_to_targets"]
            if len(grid) != len(sources) or any(len(row) != len(targets) for row in grid):
                raise ValueError("the grid is not sources x targets")
            if any("time" not in cell or "distance" not in cell for row in grid for cell in row):
                raise ValueError("a cell has no measure")
        except (ValueError, KeyError, TypeError, AttributeError) as unreadable:
            raise ProviderRejected("the routing engine's matrix answer cannot be read") from unreadable
        return grid

    def _ask(
        self, batch: tuple[int, int, Sequence[Coordinate], Sequence[Coordinate]], observer: RoutingObserver | None
    ) -> tuple[int, int, _Cells]:
        row, column, sources, targets = batch
        try:
            grid = self._post_matrix(sources, targets, observer)
        except _Unsnappable as unconnected:
            return row, column, self._without_unsnappable(sources, targets, observer, unconnected)
        return row, column, _read_grid(grid, sources, targets)

    def _without_unsnappable(
        self,
        sources: Sequence[Coordinate],
        targets: Sequence[Coordinate],
        observer: RoutingObserver | None,
        unconnected: _Unsnappable,
    ) -> _Cells:
        """Error 170 failed the whole call: locate its places, ask again without those with no edge and answer their
        cells `OffNetwork`. Nothing is remembered beyond this call."""
        off = self._locate_without_edges(list(dict.fromkeys([*sources, *targets])), observer)
        if not off:
            raise unconnected
        kept_sources, kept_targets = [p for p in sources if p not in off], [p for p in targets if p not in off]
        measured: _Cells = []
        if kept_sources and kept_targets:
            measured = _read_grid(self._post_matrix(kept_sources, kept_targets, observer), kept_sources, kept_targets)
        return [
            [
                OffNetwork(frozenset(end for end in (source, target) if end in off))
                if source in off or target in off
                else measured[kept_sources.index(source)][kept_targets.index(target)]
                for target in targets
            ]
            for source in sources
        ]

    def _locate_without_edges(self, places: list[Coordinate], observer: RoutingObserver | None) -> set[Coordinate]:
        question = {**self._question(places, []), "verbose": True}
        question = {
            "locations": question["sources"],
            **{k: question[k] for k in ("costing", "costing_options", "verbose")},
        }
        answer = self._call(
            "POST",
            "/locate",
            observer,
            json=question,
            timeout=httpx.Timeout(_OTHER_READ_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S),
        )
        if answer.status_code != httpx.codes.OK:
            raise _refusal(answer)
        try:
            located = answer.json()
            if len(located) != len(places):
                raise ValueError("one answer per place")
            return {place for place, found in zip(places, located, strict=True) if not found["edges"]}
        except (ValueError, KeyError, TypeError) as unreadable:
            raise ProviderRejected("the routing engine's locate answer cannot be read") from unreadable

    def _place(self, place: Coordinate) -> dict[str, float | int]:
        return {"lat": place.latitude, "lon": place.longitude, "search_cutoff": self._snap_m}


def _read_grid(
    grid: list[list[dict[str, Any]]], sources: Sequence[Coordinate], targets: Sequence[Coordinate]
) -> _Cells:
    try:
        return [
            [_read_cell(cell, source, target) for cell, target in zip(cells, targets, strict=True)]
            for cells, source in zip(grid, sources, strict=True)
        ]
    except (TypeError, ValueError) as unreadable:
        raise ProviderRejected("the routing engine's matrix answer cannot be read") from unreadable


def _read_cell(cell: dict[str, Any], source: Coordinate, target: Coordinate) -> RoadCell:
    if cell["time"] is None or cell["distance"] is None:
        return None
    metres, seconds = round(cell["distance"] * _METRES_PER_KM), round(cell["time"])
    if source == target:
        return RoadMeasure(distance_m=metres, duration_s=seconds)
    return RoadMeasure(distance_m=max(1, metres), duration_s=max(1, seconds))


class _Unsnappable(ProviderRejected):
    """Error 170: one place of the call is in no connected region; the whole call failed."""


def _refusal(answer: httpx.Response) -> ProviderRejected:
    try:
        body = answer.json()
        code, reason = body["error_code"], body["error"]
    except (ValueError, KeyError, TypeError):
        return ProviderRejected(f"the routing engine refused the question: HTTP {answer.status_code}")
    message = f"the routing engine refused the question: error {code}: {reason}"
    return _Unsnappable(message) if code == _UNCONNECTED_REGIONS else ProviderRejected(message)


def _degraded(reason: str) -> ProbeResult:
    return ProbeResult(outcome="degraded-healthy", reason=reason)


def _positive(measure: Any) -> bool:
    return isinstance(measure, int | float) and measure > 0

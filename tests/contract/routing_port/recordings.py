"""The recorded Valhalla 3.9.1 answers (read-only data), loaded by name for the replay and the routing-port contract.

Each JSON holds `endpoint`, `request`, `status` and `response`; `status.json` also names the recorded tileset.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from overland_planner.domain.catalog.coordinate import Coordinate

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "tests" / "contract" / "fixtures" / "valhalla-3.9.1"
REPLAY_URL = "http://valhalla.replay"


def recording(name: str) -> dict[str, Any]:
    recorded: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return recorded


class BatchLimitedEngine:
    """A scripted engine for /sources_to_targets: answers a question of at most `limit` cells, refuses a larger one
    with the recorded error 150 body, and keeps count of the questions it was asked and of how many ran at once.

    Cell (i, j) of the question, i and j being the places' positions in `sources` and `targets`, answers
    `i * 1000 + j + 1` as metres (sent as km) and as seconds, so a test knows which pair each answer belongs to.
    """

    def __init__(
        self, limit: int, sources: Sequence[Coordinate], targets: Sequence[Coordinate], *, pause_s: float = 0.0
    ) -> None:
        self._limit = limit
        self._source_index = {(p.latitude, p.longitude): i for i, p in enumerate(sources)}
        self._target_index = {(p.latitude, p.longitude): j for j, p in enumerate(targets)}
        self._pause_s = pause_s
        self._lock = threading.Lock()
        self._in_flight = 0
        self.question_sizes: list[int] = []
        self.refusals = 0
        self.most_in_flight = 0

    @staticmethod
    def measure(source_index: int, target_index: int) -> tuple[int, int]:
        """The (metres, seconds) the engine answers for the pair at those positions."""
        value = source_index * 1000 + target_index + 1
        return value, value

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        pairs = len(body["sources"]) * len(body["targets"])
        with self._lock:
            self.question_sizes.append(pairs)
            self._in_flight += 1
            self.most_in_flight = max(self.most_in_flight, self._in_flight)
        try:
            time.sleep(self._pause_s)
            if pairs > self._limit:
                with self._lock:
                    self.refusals += 1
                refusal = recording("matrix_150_pair_limit")
                return httpx.Response(refusal["status"], json=refusal["response"])
            return httpx.Response(200, json={"sources_to_targets": self._rows(body)})
        finally:
            with self._lock:
                self._in_flight -= 1

    def _rows(self, body: dict[str, Any]) -> list[list[dict[str, Any]]]:
        rows = []
        for a, source in enumerate(body["sources"]):
            row = []
            for b, target in enumerate(body["targets"]):
                metres, seconds = self.measure(
                    self._source_index[source["lat"], source["lon"]], self._target_index[target["lat"], target["lon"]]
                )
                row.append({"from_index": a, "to_index": b, "time": seconds, "distance": metres / 1000})
            rows.append(row)
        return rows

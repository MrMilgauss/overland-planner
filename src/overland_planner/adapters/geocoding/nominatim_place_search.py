"""PlaceSearch on Nominatim's `/search` (D307, D314, ADR-019).

One GET per search with exactly `q`, `format=jsonv2`, `addressdetails=1` and `limit=5`, the planner's own User-Agent and
a 10 s limit. No email, contact, coordinate or trip detail is ever sent, and a typed name is never logged.

Politeness (OSM usage policy, D307/D314): one request a second across the process (a search that would wait more than
3 s is answered busy), recent answers remembered in memory only (200 entries, 24 h, never on disk, never listed), two
identical searches at once send one, and 60 s of silence after a 429 or 503. The probe makes no outbound call: it
checks the configured address parses and that the spacing and the memory round-trip on a private fake clock.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from overland_planner.application.ports.place_search import MAX_PLACES, PlaceHit, PlaceSearchUnavailableError
from overland_planner.application.ports.probe import ProbeResult

_MISCONFIGURED = "place_search_misconfigured"
_SPACING_S = 1.0
_LONGEST_WAIT_S = 3.0
_BACK_OFF_S = 60.0
_REMEMBERED = 200
_REMEMBERED_FOR_S = 24 * 3600.0
_BUSY_CODES = (429, 503)
_REGION_KEYS = ("state", "region", "province", "state_district", "county")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _hit_of(row: object) -> PlaceHit | None:
    if not isinstance(row, dict):
        return None
    address = row.get("address")
    address = address if isinstance(address, dict) else {}
    try:
        lat, lon = float(row["lat"]), float(row["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    name = _text(row.get("name")) or _text(row.get("display_name")).split(",")[0].strip()
    if not name:
        return None
    region = next((text for key in _REGION_KEYS if (text := _text(address.get(key)))), "")
    return PlaceHit(name=name, region=region, country=_text(address.get("country")), lat=lat, lon=lon)


class _Pacing:
    """One request a second: each search reserves the next free second; too long a queue, or a back-off, refuses."""

    def __init__(self, monotonic: Callable[[], float]) -> None:
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._next_slot = float("-inf")
        self._quiet_until = float("-inf")

    def reserve(self) -> float:
        """Seconds to wait before sending; raises when the service is resting or the queue is too long."""
        with self._lock:
            now = self._monotonic()
            if now < self._quiet_until:
                raise PlaceSearchUnavailableError("the search service is being left alone")
            slot = max(now, self._next_slot)
            if slot - now > _LONGEST_WAIT_S:
                raise PlaceSearchUnavailableError("the search service is busy with other searches")
            self._next_slot = slot + _SPACING_S
            return slot - now

    def resting(self) -> bool:
        with self._lock:
            return self._monotonic() < self._quiet_until

    def leave_alone(self) -> None:
        with self._lock:
            self._quiet_until = self._monotonic() + _BACK_OFF_S


class _Memory:
    """Recent answers, in memory only; the oldest goes first."""

    def __init__(self, monotonic: Callable[[], float]) -> None:
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, tuple[float, tuple[PlaceHit, ...]]] = OrderedDict()

    def recall(self, key: str) -> tuple[PlaceHit, ...] | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if self._monotonic() >= entry[0]:
                del self._entries[key]
                return None
            return entry[1]

    def remember(self, key: str, hits: tuple[PlaceHit, ...]) -> None:
        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = (self._monotonic() + _REMEMBERED_FOR_S, hits)
            while len(self._entries) > _REMEMBERED:
                self._entries.popitem(last=False)


class _Flight:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.hits: tuple[PlaceHit, ...] = ()
        self.error: PlaceSearchUnavailableError | None = None


class NominatimPlaceSearch:
    def __init__(
        self,
        url: str,
        *,
        user_agent: str,
        timeout_s: float = 10.0,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = url
        self._headers = {"User-Agent": user_agent}
        self._timeout_s = timeout_s
        self._sleep = sleep
        self._pacing = _Pacing(monotonic)
        self._memory = _Memory(monotonic)
        self._flights: dict[str, _Flight] = {}
        self._flights_lock = threading.Lock()

    def search(self, words: str) -> tuple[PlaceHit, ...]:
        key = " ".join(words.split()).casefold()
        remembered = self._memory.recall(key)
        if remembered is not None:
            return remembered
        with self._flights_lock:
            flight = self._flights.get(key)
            leading = flight is None
            if flight is None:
                flight = self._flights[key] = _Flight()
        if not leading:
            flight.done.wait()
            if flight.error is not None:
                raise flight.error
            return flight.hits
        try:
            flight.hits = self._ask(words)
            self._memory.remember(key, flight.hits)
            return flight.hits
        except PlaceSearchUnavailableError as unavailable:
            flight.error = unavailable
            raise
        finally:
            with self._flights_lock:
                del self._flights[key]
            flight.done.set()

    def _ask(self, words: str) -> tuple[PlaceHit, ...]:
        wait = self._pacing.reserve()
        if wait > 0:
            self._sleep(wait)
        if self._pacing.resting():
            raise PlaceSearchUnavailableError("the search service is being left alone")
        params = {"q": words, "format": "jsonv2", "addressdetails": "1", "limit": str(MAX_PLACES)}
        try:
            with httpx.Client(headers=self._headers, timeout=self._timeout_s) as client:
                answer = client.get(self._url, params=params)
            if answer.status_code in _BUSY_CODES:
                self._pacing.leave_alone()
            if answer.status_code != httpx.codes.OK:
                raise PlaceSearchUnavailableError("the search service did not answer")
            rows: Any = answer.json()
        except (httpx.HTTPError, ValueError):
            raise PlaceSearchUnavailableError("the search service did not give a readable answer") from None
        if not isinstance(rows, list):
            raise PlaceSearchUnavailableError("the search service did not give a list")
        hits = (_hit_of(row) for row in rows)
        return tuple(hit for hit in hits if hit is not None)[:MAX_PLACES]

    def probe(self) -> ProbeResult:
        parts = urlsplit(self._url)
        try:
            usable = parts.scheme in ("http", "https") and bool(parts.hostname) and parts.port != 0
        except ValueError:
            usable = False
        if not usable or not _politeness_round_trips():
            return ProbeResult(outcome="degraded-healthy", reason=_MISCONFIGURED)
        return ProbeResult(outcome="ok")


def _politeness_round_trips() -> bool:
    """The spacing and the memory on a private fake clock: nothing is sent and the live ones are not touched."""
    now = [0.0]
    pacing, memory = _Pacing(lambda: now[0]), _Memory(lambda: now[0])
    first, second = pacing.reserve(), pacing.reserve()
    memory.remember("probe", ())
    recalled = memory.recall("probe") == ()
    now[0] += _REMEMBERED_FOR_S
    return first == 0 and second == _SPACING_S and recalled and memory.recall("probe") is None


class SwitchedOffPlaceSearch:
    """PLACE_SEARCH=off: nothing is ever sent."""

    def search(self, words: str) -> tuple[PlaceHit, ...]:
        raise PlaceSearchUnavailableError("place search is switched off")

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok", reason="switched off")

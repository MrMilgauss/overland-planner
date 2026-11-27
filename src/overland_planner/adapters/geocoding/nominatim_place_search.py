"""PlaceSearch on Nominatim's `/search` (D307, D314, ADR-019).

One GET per search with exactly `q`, `format=jsonv2`, `addressdetails=1` and `limit=5`, the planner's own User-Agent and
a 10 s limit. No email, contact, coordinate or trip detail is ever sent, and a typed name is never logged. The probe
makes no outbound call: it checks the configured address parses.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from overland_planner.application.ports.place_search import MAX_PLACES, PlaceHit, PlaceSearchUnavailableError
from overland_planner.application.ports.probe import ProbeResult

_MISCONFIGURED = "place_search_misconfigured"
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


class NominatimPlaceSearch:
    def __init__(self, url: str, *, user_agent: str, timeout_s: float = 10.0) -> None:
        self._url = url
        self._headers = {"User-Agent": user_agent}
        self._timeout_s = timeout_s

    def search(self, words: str) -> tuple[PlaceHit, ...]:
        params = {"q": words, "format": "jsonv2", "addressdetails": "1", "limit": str(MAX_PLACES)}
        try:
            with httpx.Client(headers=self._headers, timeout=self._timeout_s) as client:
                answer = client.get(self._url, params=params)
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
        return ProbeResult(outcome="ok") if usable else ProbeResult(outcome="degraded-healthy", reason=_MISCONFIGURED)


class SwitchedOffPlaceSearch:
    """PLACE_SEARCH=off: nothing is ever sent."""

    def search(self, words: str) -> tuple[PlaceHit, ...]:
        raise PlaceSearchUnavailableError("place search is switched off")

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok", reason="switched off")

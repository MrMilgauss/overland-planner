"""RegionCatalogue on Geofabrik's index (D306, D310, D315): the free list of regions, kept on disk for a week.

The list (`index-v1-nogeom.json`: per feature `id`, `name`, `parent`, `urls.pbf`, `urls.poly`) is fetched with one GET,
no query, the planner's own User-Agent and a 10 s limit, and kept in the planner's data folder; a restarted planner
reads the kept copy, a copy older than a week is fetched again, and when that fails the kept copy is used. A kept copy
that does not read is discarded. A region's size is one HEAD of its `.osm.pbf`, remembered a week in memory. One request
runs at a time, and only addresses under the list's own origin are ever asked, so nothing but region details leaves.
This adapter parses data only; a feature without a `.osm.pbf` or `.poly` address, with an address off the origin, or
whose parent chain does not end at a region of the list is not offered. The probe is degraded, never fatal, and reads
the kept copy or fetches once.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from overland_planner.adapters.roadmap.poly_parser import PolyParseError, parse_poly
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.region_catalogue import CatalogueEntry, CatalogueUnavailableError
from overland_planner.domain.roadmap.outline import Outline

KEPT_FILE = "geofabrik-index.json"
BORDERS_FOLDER = "borders"
KEPT_FOR = timedelta(days=7).total_seconds()
DEFAULT_MIN_FEATURES = 100
_UNAVAILABLE = "region_catalogue_unavailable"


class _BadIndexError(ValueError):
    """Text that is not a list of regions."""


@dataclass(frozen=True)
class _Feature:
    key: str
    name: str
    parent: str | None
    pbf: str | None
    poly: str | None


@dataclass(frozen=True)
class _Index:
    features: tuple[_Feature, ...]
    origin: str

    @classmethod
    def read(cls, text: str, origin: str) -> _Index:
        try:
            data = json.loads(text)
        except ValueError:
            raise _BadIndexError("not JSON") from None
        raw = data.get("features") if isinstance(data, dict) else None
        found = tuple(feature for feature in map(_feature, raw if isinstance(raw, list) else []) if feature)
        if not found:
            raise _BadIndexError("no region")
        return cls(found, origin)

    def offered(self) -> tuple[CatalogueEntry, ...]:
        by_key = self._by_key()
        entries = (
            CatalogueEntry(f.key, f.name, f.parent, f.pbf, f.poly)
            for f in by_key.values()
            if f.pbf is not None and f.poly is not None and self._own(f.pbf, f.poly) and self._rooted(f, by_key)
        )
        return tuple(entries)

    def fault(self, min_features: int) -> str | None:
        by_key = self._by_key()
        if len(by_key) != len(self.features):
            return "duplicate key"
        if not all(self._own(*[a for a in (f.pbf, f.poly) if a is not None]) for f in self.features):
            return "address off the origin"
        if any(f.parent is not None and f.parent not in by_key for f in self.features):
            return "parent does not resolve"
        if len(self.offered()) < min_features:
            return "fewer features than expected"
        return None

    def _by_key(self) -> dict[str, _Feature]:
        first: dict[str, _Feature] = {}
        for feature in self.features:
            first.setdefault(feature.key, feature)
        return first

    def _own(self, *addresses: str) -> bool:
        return all(address.startswith(self.origin) for address in addresses)

    @staticmethod
    def _rooted(feature: _Feature, by_key: dict[str, _Feature]) -> bool:
        seen: set[str] = {feature.key}
        parent = feature.parent
        while parent is not None:
            if parent in seen or parent not in by_key:
                return False
            seen.add(parent)
            parent = by_key[parent].parent
        return True


def _feature(raw: Any) -> _Feature | None:
    properties = raw.get("properties") if isinstance(raw, dict) else None
    if not isinstance(properties, dict):
        return None
    key, name, parent = properties.get("id"), properties.get("name"), properties.get("parent")
    urls = properties.get("urls")
    urls = urls if isinstance(urls, dict) else {}
    if not (isinstance(key, str) and key and isinstance(name, str) and name):
        return None
    if not (parent is None or isinstance(parent, str)):
        return None
    return _Feature(key, name, parent, _address(urls.get("pbf")), _address(urls.get("poly")))


def _address(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class _Kept:
    fetched_at: float
    index: _Index


class GeofabrikCatalogue:
    def __init__(
        self,
        index_url: str,
        folder: Path,
        clock: Clock,
        *,
        user_agent: str,
        min_features: int = DEFAULT_MIN_FEATURES,
        timeout_s: float = 10.0,
    ) -> None:
        parts = urlsplit(index_url)
        self._index_url = index_url
        self._origin = f"{parts.scheme}://{parts.netloc}/"
        self._file = folder / KEPT_FILE
        self._borders = folder / BORDERS_FOLDER
        self._clock = clock
        self._headers = {"User-Agent": user_agent}
        self._min_features = min_features
        self._timeout_s = timeout_s
        self._lock = threading.Lock()  # one request at a time, and one load at a time
        self._kept: _Kept | None = None
        self._sizes: dict[str, tuple[str, int, float]] = {}

    def entries(self) -> tuple[CatalogueEntry, ...]:
        with self._lock:
            return self._current().offered()

    def size_of(self, entry: CatalogueEntry) -> int | None:
        with self._lock:
            now = self._clock.now().timestamp()
            known = self._sizes.get(entry.key)
            if known is not None and known[0] == entry.pbf_url and now - known[2] < KEPT_FOR:
                return known[1]
            size = self._head(entry.pbf_url)
            if size is not None:
                self._sizes[entry.key] = (entry.pbf_url, size, now)
            return size

    def outline_of(self, entry: CatalogueEntry) -> Outline:
        """The region's border: read from the disk when kept (a copy that does not read is discarded), else one GET of
        its `.poly` under the list's own origin, kept only once it reads."""
        with self._lock:
            kept = self._borders / (hashlib.sha256(entry.poly_url.encode()).hexdigest() + ".poly")
            try:
                return parse_poly(kept.read_text(encoding="utf-8"))
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                kept.unlink(missing_ok=True)
            text = self._get_text(entry.poly_url)
            try:
                outline = parse_poly(text)
            except PolyParseError:
                raise CatalogueUnavailableError(f"the border of {entry.name} does not read") from None
            self._keep_text(kept, text)
            return outline

    def probe(self) -> ProbeResult:
        try:
            with self._lock:
                fault = self._current().fault(self._min_features)
        except CatalogueUnavailableError:
            return ProbeResult(outcome="degraded-healthy", reason=_UNAVAILABLE)
        if fault is not None:
            return ProbeResult(outcome="degraded-healthy", reason=_UNAVAILABLE)
        return ProbeResult(outcome="ok")

    def _current(self) -> _Index:
        now = self._clock.now().timestamp()
        kept = self._kept or self._read_kept()
        if kept is not None and now - kept.fetched_at < KEPT_FOR:
            self._kept = kept
            return kept.index
        fetched = self._fetch(now)
        if fetched is not None:
            self._kept = fetched
            return fetched.index
        if kept is None:
            raise CatalogueUnavailableError("the list of regions is not kept and the region service gave none")
        self._kept = kept
        return kept.index

    def _read_kept(self) -> _Kept | None:
        try:
            envelope = json.loads(self._file.read_text(encoding="utf-8"))
            if envelope["index_url"] != self._index_url:
                raise _BadIndexError("kept for another address")
            return _Kept(float(envelope["fetched_at"]), _Index.read(envelope["body"], self._origin))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            self._file.unlink(missing_ok=True)  # a copy that does not read is discarded
            return None

    def _fetch(self, now: float) -> _Kept | None:
        try:
            with httpx.Client(headers=self._headers, timeout=self._timeout_s) as client:
                answer = client.get(self._index_url)
            if answer.status_code != httpx.codes.OK:
                return None
            index = _Index.read(answer.text, self._origin)
        except (httpx.HTTPError, _BadIndexError):
            return None
        self._keep(now, answer.text)
        return _Kept(now, index)

    def _keep(self, now: float, body: str) -> None:
        envelope = {"index_url": self._index_url, "fetched_at": now, "body": body}
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            partial = self._file.with_name(self._file.name + ".part")
            partial.write_text(json.dumps(envelope), encoding="utf-8")
            os.replace(partial, self._file)
        except OSError:
            return  # not kept: the list stays in memory and is fetched again after a restart

    def _get_text(self, address: str) -> str:
        if not address.startswith(self._origin):
            raise CatalogueUnavailableError("a border is only asked of the list's own service")
        try:
            with httpx.Client(headers=self._headers, timeout=self._timeout_s) as client:
                answer = client.get(address)
        except httpx.HTTPError:
            raise CatalogueUnavailableError("the region service did not give a border") from None
        if answer.status_code != httpx.codes.OK:
            raise CatalogueUnavailableError("the region service did not give a border")
        return answer.text

    @staticmethod
    def _keep_text(file: Path, text: str) -> None:
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            partial = file.with_name(file.name + ".part")
            partial.write_text(text, encoding="utf-8")
            os.replace(partial, file)
        except OSError:
            return  # not kept: asked again next time

    def _head(self, address: str) -> int | None:
        try:
            with httpx.Client(headers=self._headers, timeout=self._timeout_s) as client:
                answer = client.head(address)
            size = int(answer.headers["content-length"])
        except (httpx.HTTPError, KeyError, ValueError):
            return None
        return size if answer.status_code == httpx.codes.OK and size >= 0 else None

"""Test-side doubles and fixture builders of slice 12c (US-27 to US-30). Complete, not scaffolds.

- `RecordingServer`: a local HTTP server that records every request (path, query, headers, monotonic arrival time). Two
  uses: the region service (Geofabrik: the index, `.poly` outlines, one HEAD per region for its size) and the place
  search
  service (Nominatim `/search`). They are external, non-deterministic ports (policy row "Region catalogue and place
  search"), so they are faked at the network edge: the real adapters run against real HTTP on a loopback port.
- `build_volume`: a tileset folder as the refresh leaves it (`tilesets/<name>/` with `road-map.json`, `outlines/*.poly`
  and, for the real reader, a `valhalla_tiles.tar` whose modification time is the map date).
- `gpx_of`: a minimal GPX file through named points.

Region sizes are the fixture's (decimal GB), chosen so that today's eight regions add up to 6.4 GB (D297's measure).
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "road-map"
GEOFABRIK = "https://download.geofabrik.de/"
GB = 1_000_000_000

# key = the folder of the region's .osm.pbf address in the index (D306), size in GB
SIZES_GB: dict[str, float] = {
    "italy": 2.2,
    "spain": 1.4,
    "switzerland": 0.5,
    "austria": 0.7,
    "rhone-alpes": 0.5,
    "provence-alpes-cote-d-azur": 0.4,
    "languedoc-roussillon": 0.3,
    "midi-pyrenees": 0.4,
    "portugal": 0.4,
    "andorra": 0.01,
    "france": 3.5,
    "germany": 4.2,
    "georgia": 0.03,
    "europe": 30.0,
    "north-america": 14.0,
    "us": 11.0,
    "us/utah": 1.1,
    "us/georgia": 0.5,
    "us/california": 1.2,
}
EIGHT = (
    "italy",
    "spain",
    "switzerland",
    "austria",
    "rhone-alpes",
    "provence-alpes-cote-d-azur",
    "languedoc-roussillon",
    "midi-pyrenees",
)


def catalogue_features() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "geofabrik-index-trimmed.json").read_text(encoding="utf-8"))["features"]


def key_of(feature: dict[str, Any]) -> str:
    """The region key is the Geofabrik index `id` (D315)."""
    return str(feature["properties"]["id"])


def feature_by_key(key: str) -> dict[str, Any]:
    return next(f for f in catalogue_features() if key_of(f) == key)


def feature_named(name: str, parent: str | None = None) -> dict[str, Any]:
    found = [f for f in catalogue_features() if f["properties"]["name"] == name]
    if parent is not None:
        found = [f for f in found if f["properties"]["parent"] == parent]
    assert found, f"the fixture catalogue has no region named {name!r}"
    return found[0]


def poly_file_of(feature: dict[str, Any]) -> Path:
    return FIXTURES / "poly" / feature["properties"]["urls"]["poly"].rsplit("/", 1)[1]


@dataclass
class Seen:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    at: float


Responder = Callable[[Seen], tuple[int, dict[str, str], bytes]]


@dataclass
class RecordingServer:
    """A loopback HTTP server that records what it is asked and answers with `responder`."""

    responder: Responder
    seen: list[Seen] = field(default_factory=list)
    _server: ThreadingHTTPServer | None = None
    _port: int = 0

    def start(self) -> RecordingServer:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                parts = urlsplit(self.path)
                record = Seen(
                    self.command,
                    parts.path,
                    parse_qs(parts.query),
                    {k.lower(): v for k, v in self.headers.items()},
                    time.monotonic(),
                )
                outer.seen.append(record)
                status, headers, body = outer.responder(record)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(headers.get("X-Length", len(body))))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            do_GET = do_HEAD = _answer

            def log_message(self, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    @property
    def url(self) -> str:
        """Kept after `stop()`: a stopped server is an address nobody answers at."""
        assert self._port, "the fake server was never started"
        return f"http://127.0.0.1:{self._port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def requests(self, method: str | None = None, path_contains: str = "") -> list[Seen]:
        return [s for s in self.seen if (method is None or s.method == method) and path_contains in s.path]


# ------------------------------------------------------------------------------------------------ the region service
def region_service() -> RecordingServer:
    """Geofabrik as the planner meets it: the index (its addresses point at this server), the outlines, one HEAD a region."""  # noqa: E501
    holder: dict[str, RecordingServer] = {}

    def respond(seen: Seen) -> tuple[int, dict[str, str], bytes]:
        base = holder["server"].url + "/"
        if seen.path.endswith("index-v1-nogeom.json"):
            text = (FIXTURES / "geofabrik-index-trimmed.json").read_text(encoding="utf-8").replace(GEOFABRIK, base)
            return 200, {"Content-Type": "application/json"}, text.encode()
        if seen.path.endswith(".poly") and seen.method == "GET":
            wanted = FIXTURES / "poly" / seen.path.rsplit("/", 1)[1]
            return (200, {}, wanted.read_bytes()) if wanted.is_file() else (404, {}, b"not found")
        if seen.path.endswith("-latest.osm.pbf") and seen.method == "HEAD":
            for feature in catalogue_features():
                if feature["properties"]["urls"]["pbf"].removeprefix(GEOFABRIK) == seen.path.lstrip("/"):
                    return 200, {"X-Length": str(int(SIZES_GB[key_of(feature)] * GB))}, b""
        return 404, {}, b"not found"

    holder["server"] = RecordingServer(respond)
    return holder["server"].start()


# ------------------------------------------------------------------------------------------- the place search service
PLACES: dict[str, list[dict[str, Any]]] = {
    "gorges du verdon": [
        {
            "place_id": 1,
            "lat": "43.7500",
            "lon": "6.3300",
            "name": "Gorges du Verdon",
            "display_name": "Gorges du Verdon, Alpes-de-Haute-Provence, Provence-Alpes-Cote d'Azur, France",
            "address": {"state": "Provence-Alpes-Cote d'Azur", "country": "France", "country_code": "fr"},
        }
    ],
    "lagos": [
        {
            "place_id": 2,
            "lat": "37.1028",
            "lon": "-8.6730",
            "name": "Lagos",
            "display_name": "Lagos, Faro, Algarve, Portugal",
            "address": {"state": "Algarve", "country": "Portugal", "country_code": "pt"},
        },
        {
            "place_id": 3,
            "lat": "6.4550",
            "lon": "3.3841",
            "name": "Lagos",
            "display_name": "Lagos, Lagos State, Nigeria",
            "address": {"state": "Lagos State", "country": "Nigeria", "country_code": "ng"},
        },
    ],
    "zxqvbn": [],
}


def place_search_service(mode: str = "healthy") -> RecordingServer:
    """Nominatim's `/search`. `mode`: healthy, busy (429), error (500), nonsense (200 with a body that is not JSON)."""

    def respond(seen: Seen) -> tuple[int, dict[str, str], bytes]:
        if mode == "busy":
            return 429, {}, b"slow down"
        if mode == "error":
            return 500, {}, b"broken"
        if mode == "nonsense":
            return 200, {"Content-Type": "application/json"}, b"<html>not json</html>"
        words = seen.query.get("q", [""])[0].lower()
        return 200, {"Content-Type": "application/json"}, json.dumps(PLACES.get(words, [])).encode()

    return RecordingServer(respond).start()


# ------------------------------------------------------------------------------------------------ fixture volumes
def record_of(keys: list[str], tileset: str) -> dict[str, Any]:
    regions = []
    for key in keys:
        feature = feature_by_key(key)
        props = feature["properties"]
        parent = next((f for f in catalogue_features() if f["properties"]["id"] == props["parent"]), None)
        regions.append(
            {
                "key": key,
                "name": props["name"],
                "parent_name": parent["properties"]["name"] if parent else None,
                "pbf_url": props["urls"]["pbf"],
                "outline": poly_file_of(feature).name,
                "bytes": int(SIZES_GB[key] * GB),
            }
        )
    return {"schema": 1, "regions": regions}


def build_volume(
    root: Path,
    tilesets: dict[str, tuple[list[str], datetime]],
    *,
    with_tar: bool = False,
) -> Path:
    """`root/tilesets/<name>/road-map.json` + `outlines/` for each tileset; the map date is the tar's (or record's) mtime."""  # noqa: E501
    base = root / "tilesets"
    base.mkdir(parents=True, exist_ok=True)
    for name, (keys, built_at) in tilesets.items():
        folder = base / name
        (folder / "outlines").mkdir(parents=True, exist_ok=True)
        record = folder / "road-map.json"
        record.write_text(json.dumps(record_of(keys, name)), encoding="utf-8")
        for key in keys:
            source = poly_file_of(feature_by_key(key))
            (folder / "outlines" / source.name).write_bytes(source.read_bytes())
        stamp = built_at.astimezone(UTC).timestamp()
        record_files = [record]
        if with_tar:
            tar = folder / "valhalla_tiles.tar"
            tar.write_bytes(b"tiles " + name.encode())
            record_files.append(tar)
        for path in record_files:
            os.utime(path, (stamp, stamp))
    return base


def epoch_of(tileset_dir: Path) -> int:
    return int((tileset_dir / "valhalla_tiles.tar").stat().st_mtime)


def gpx_of(name: str, points: list[tuple[float, float]]) -> bytes:
    """A track through the points (each leg cut in five), as a GPX 1.1 file the importer reads."""
    dense: list[tuple[float, float]] = []
    for (a_lat, a_lon), (b_lat, b_lon) in itertools.pairwise(points):
        for step in range(5):
            f = step / 5
            dense.append((a_lat + (b_lat - a_lat) * f, a_lon + (b_lon - a_lon) * f))
    dense.append(points[-1])
    body = "".join(f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}"></trkpt>' for lat, lon in dense)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="slice-12c-test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><name>{name}</name><trkseg>{body}</trkseg></trk></gpx>"
    ).encode()

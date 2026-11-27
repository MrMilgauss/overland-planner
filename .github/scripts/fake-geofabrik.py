#!/usr/bin/env python3
"""A small local stand-in for Geofabrik, for the browser checks of CI job 7 and of a local run (slice 12c).

  python .github/scripts/fake-geofabrik.py [PORT] [HOST]     (default 8766 on 127.0.0.1)

The planner's GEOFABRIK_INDEX_URL points at `http://<host>:<port>/index-v1-nogeom.json`; no browser check ever asks the
real service. It serves, from tests/acceptance/overland_route_planner_mvp/fixtures/road-map/:
  - `GET /index-v1-nogeom.json`: the trimmed index with every address moved to the origin the request came to
    (the planner only asks the origin of its own index, D306/D315); the paths are kept. The planner's own check wants
    100 regions before it calls the list healthy, so the answer also holds spare regions named "Spare region NNN"
    under Europe, which no spec searches for;
  - `GET <poly path>`: the region outlines of `poly/` (a spare region gets Andorra's);
  - `HEAD <pbf path>`: the region's size as Content-Length (the sizes the acceptance steps use; a spare region 0.1 GB);
  - `GET /__requests`: every `METHOD path` received, in order; `DELETE /__requests` empties the log.
Standard library only.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

FIXTURES = Path(__file__).resolve().parents[2] / "tests/acceptance/overland_route_planner_mvp/fixtures/road-map"
GEOFABRIK = "https://download.geofabrik.de/"
GB = 1_000_000_000
SPARE = 90

# region id -> size in GB (the same as steps/road_map_fakes.py: today's eight regions add up to 6.4 GB)
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

REQUESTS: list[str] = []
LOCK = threading.Lock()


def _spare(number: int) -> dict[str, object]:
    key = f"spare-{number:03d}"
    return {
        "type": "Feature",
        "properties": {
            "id": key,
            "name": f"Spare region {number:03d}",
            "parent": "europe",
            "urls": {
                "poly": f"{GEOFABRIK}europe/{key}/{key}.poly",
                "pbf": f"{GEOFABRIK}europe/{key}/{key}-latest.osm.pbf",
            },
        },
        "geometry": None,
    }


def index_text(origin: str) -> str:
    text = (FIXTURES / "geofabrik-index-trimmed.json").read_text(encoding="utf-8")
    body = json.loads(text)
    body["features"] = body["features"] + [_spare(number) for number in range(1, SPARE + 1)]
    return json.dumps(body).replace(GEOFABRIK, origin + "/")


def size_of(path: str) -> int | None:
    """The size of the region whose `-latest.osm.pbf` address is this path, or None."""
    if not path.endswith("-latest.osm.pbf"):
        return None
    text = (FIXTURES / "geofabrik-index-trimmed.json").read_text(encoding="utf-8")
    for feature in json.loads(text)["features"]:
        if feature["properties"]["urls"]["pbf"].removeprefix(GEOFABRIK) == path.lstrip("/"):
            return int(SIZES_GB[feature["properties"]["id"]] * GB)
    return int(0.1 * GB) if "/spare-" in path else None


class Handler(BaseHTTPRequestHandler):
    def _reply(
        self, status: int, body: bytes = b"", kind: str = "application/octet-stream", length: int | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body) if length is None else length))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _log(self) -> str:
        path = urlsplit(self.path).path
        with LOCK:
            REQUESTS.append(f"{self.command} {path}")
        return path

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/__requests":
            with LOCK:
                self._reply(200, json.dumps(list(REQUESTS)).encode(), "application/json")
            return
        self._log()
        if path.endswith("index-v1-nogeom.json"):
            origin = f"http://{self.headers.get('Host', '127.0.0.1')}"
            self._reply(200, index_text(origin).encode(), "application/json")
        elif path.endswith(".poly"):
            name = "andorra.poly" if "/spare-" in path else path.rsplit("/", 1)[1]
            wanted = FIXTURES / "poly" / name
            if wanted.is_file():
                self._reply(200, wanted.read_bytes(), "text/plain")
            else:
                self._reply(404, b"not found", "text/plain")
        else:
            self._reply(404, b"not found", "text/plain")

    def do_HEAD(self) -> None:
        path = self._log()
        size = size_of(path)
        if size is None:
            self._reply(404, b"", "text/plain")
        else:
            self._reply(200, b"", "application/octet-stream", length=size)

    def do_DELETE(self) -> None:
        if urlsplit(self.path).path != "/__requests":
            self._reply(404, b"not found", "text/plain")
            return
        with LOCK:
            REQUESTS.clear()
        self._reply(200, b"[]", "application/json")

    def log_message(self, format: str, *args: object) -> None:
        return


def main(port: int, host: str) -> None:
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8766, sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1")

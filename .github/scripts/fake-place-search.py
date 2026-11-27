#!/usr/bin/env python3
"""A small local stand-in for Nominatim's `/search`, for the browser checks of CI job 7 and of a local run (slice 12c).

  python .github/scripts/fake-place-search.py [PORT] [HOST]     (default 8765 on 127.0.0.1)

The planner's PLACE_SEARCH_URL points at `http://<host>:<port>/search`; no browser check ever asks the real service.
`GET /search?q=...` answers jsonv2 rows shaped like the recorded real answer
(tests/unit/adapters/geocoding/fixtures/nominatim-moab-jsonv2.json) for the words the specs type: a query containing
"gorges du verdon" gets the one place in Provence-Alpes-Cote d'Azur (France, inside the fixture map), "lagos" gets Lagos
in Portugal and in Nigeria (outside it), anything else (such as "zxqvbn") an empty list. `GET /__requests` lists every
`q` received, in order, so a spec can read what was sent; `DELETE /__requests` empties the log. Standard library only.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

LICENCE = "Data © OpenStreetMap contributors, ODbL 1.0. http://osm.org/copyright"


def _row(place_id: int, name: str, lat: str, lon: str, state: str, country: str, code: str) -> dict[str, object]:
    return {
        "place_id": place_id,
        "licence": LICENCE,
        "osm_type": "node",
        "osm_id": place_id,
        "lat": lat,
        "lon": lon,
        "category": "place",
        "type": "locality",
        "place_rank": 20,
        "importance": 0.4,
        "addresstype": "locality",
        "name": name,
        "display_name": f"{name}, {state}, {country}",
        "address": {"locality": name, "state": state, "country": country, "country_code": code},
        "boundingbox": [lat, lat, lon, lon],
    }


ANSWERS: tuple[tuple[str, list[dict[str, object]]], ...] = (
    (
        "gorges du verdon",
        [_row(1001, "Gorges du Verdon", "43.7686", "6.3322", "Provence-Alpes-Côte d'Azur", "France", "fr")],
    ),
    (
        "lagos",
        [
            _row(1002, "Lagos", "37.1028", "-8.6742", "Algarve", "Portugal", "pt"),
            _row(1003, "Lagos", "6.4550", "3.3841", "Lagos State", "Nigeria", "ng"),
        ],
    ),
)

REQUESTS: list[str] = []
LOCK = threading.Lock()


def answer_for(words: str) -> list[dict[str, object]]:
    wanted = " ".join(words.split()).casefold()
    return next((rows for key, rows in ANSWERS if key in wanted), [])


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: object) -> None:
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        if parts.path == "/__requests":
            with LOCK:
                self._send(list(REQUESTS))
        elif parts.path == "/search":
            words = parse_qs(parts.query).get("q", [""])[0]
            with LOCK:
                REQUESTS.append(words)
            self._send(answer_for(words))
        else:
            self.send_error(404)

    def do_DELETE(self) -> None:
        if urlsplit(self.path).path != "/__requests":
            self.send_error(404)
            return
        with LOCK:
            REQUESTS.clear()
        self._send([])

    def log_message(self, format: str, *args: object) -> None:
        return


def main(port: int, host: str) -> None:
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8765, sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1")

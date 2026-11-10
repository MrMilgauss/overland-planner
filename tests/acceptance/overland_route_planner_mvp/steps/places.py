"""Named places and trail files used by the scenarios (production-like data of slice 01a).

Entry/exit names such as "Pian dell'Alpe" are checked by coordinates (DISTILL D109): a trail runs "from A to B"
when its entry lies within ENTRY_EXIT_TOLERANCE_M of place A and its exit within that distance of place B.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "gpx"
ROAD_MAPS = FIXTURES.parent / "road-maps"
ENTRY_EXIT_TOLERANCE_M = 50.0


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float


PLACES = {
    p.name: p
    for p in (
        Place("Pian dell'Alpe", 45.0560, 7.0410),
        Place("Sestriere", 44.9580, 6.8790),
        Place("Casa Marco, Torino", 45.0703, 7.6869),
        Place("Briancon", 44.8990, 6.6430),
        Place("Aosta", 45.7370, 7.3200),
        # slice 02
        Place("Hotel Sestriere", 44.9580, 6.8790),
        Place("Rifugio Pian dell'Alpe", 45.0560, 7.0410),
        Place("Bardonecchia", 45.0780, 6.7040),
        Place("Cortina d'Ampezzo", 46.5405, 12.1357),
        Place("Lago di Braies", 46.6943, 12.0855),
        Place("Passo Giau", 46.4836, 12.0539),
        Place("Passo Falzarego", 46.5192, 12.0086),
        Place("Rifugio Auronzo", 46.6125, 12.2953),
        Place("Misurina", 46.5819, 12.2531),
        Place("Passo Valparola", 46.5317, 11.9917),
        Place("Cuneo", 44.3845, 7.5427),
        # slice 03b (synthetic dead-end trails, D198): Rochemolles -> Colle del Sommeiller 12.4 km, Bardonecchia ->
        # Rifugio III Alpini (the Valle Stretta trail) 9.6 km
        Place("Rochemolles", 45.1180, 6.8870),
        Place("Colle del Sommeiller", 45.1520, 7.0376),
        Place("Rifugio III Alpini", 45.0450, 6.5911),
    )
}


@dataclass(frozen=True)
class TrailFile:
    """A GPX file of the corpus. `reference_length_km` is what Marco's GPX viewer reports for it."""

    file_name: str
    track_name: str | None = None
    reference_length_km: float | None = None
    synthetic: bool = True  # DISTILL D112: synthetic stand-ins until Marco's real corpus is committed


TRAIL_FILES = {
    "assietta.gpx": TrailFile("assietta.gpx", "Strada dell'Assietta", 34.2),
    "notes.gpx": TrailFile("notes.gpx"),
    "empty.gpx": TrailFile("empty.gpx"),
    "waypoints-only.gpx": TrailFile("waypoints-only.gpx"),
    "trap.gpx": TrailFile("trap.gpx"),
    # slice 02 (D198: synthetic, generated for the scenarios' numbers; never a third party's recording)
    "jafferau-loop.gpx": TrailFile("jafferau-loop.gpx", "Jafferau loop", 18.9),
    "maira-varaita-ridge.gpx": TrailFile("maira-varaita-ridge.gpx", "Maira-Varaita ridge", 69.5),
    # slice 03b (D198: synthetic dead-end trails, recorded uphill)
    "colle-del-sommeiller.gpx": TrailFile("colle-del-sommeiller.gpx", "Colle del Sommeiller", 12.4),
    "valle-stretta.gpx": TrailFile("valle-stretta.gpx", "Valle Stretta", 9.6),
}


def trail_file_bytes(file_name: str) -> bytes:
    return (FIXTURES / file_name).read_bytes()


def oversized_gpx_bytes(megabytes: int) -> bytes:
    """A well-formed GPX file just above `megabytes` MB (generated, never committed)."""
    head = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="overland-planner DISTILL fixture" xmlns="http://www.topografix.com/GPX/1/1">\n'
        "  <trk><name>Huge</name><trkseg>\n"
    )
    tail = "  </trkseg></trk>\n</gpx>\n"
    point = '    <trkpt lat="45.000000" lon="7.000000"><ele>1000.0</ele></trkpt>\n'
    target = megabytes * 1024 * 1024 + 1
    count = (target - len(head) - len(tail)) // len(point) + 1
    return (head + point * count + tail).encode()


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance; the test's own oracle for 'is this point at that place'."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))

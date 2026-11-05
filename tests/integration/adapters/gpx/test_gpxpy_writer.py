"""`GpxpyWriter` writes real GPX 1.1 bytes, read back with defusedxml and the vendored XSD (brief §6, ADR-010).

Integration level: single examples through the `GpxWriter` contract, plus one property over any name and any Alpine
point list; the start-up refusal is checked through `create_app`.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Iterator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as safe_xml
import pytest
import xmlschema
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from overland_planner.adapters.gpx.gpxpy_writer import GpxpyWriter
from overland_planner.application.ports.gpx_writer import GpxWriter
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.bootstrap import app_factory
from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from overland_planner.bootstrap.startup import StartupRefusedError
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.export.gpx_document import GpxDocument, GpxTrack, GpxWaypoint
from tests.common.fakes import FakeClock, FakeMountTable
from tests.common.workspace import workspace_data_dir

REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA = xmlschema.XMLSchema(
    str(REPO_ROOT / "tests" / "acceptance" / "overland_route_planner_mvp" / "fixtures" / "schemas" / "gpx-1.1.xsd")
)
NS = "{http://www.topografix.com/GPX/1/1}"
WRITER: GpxWriter = GpxpyWriter()
PLAIN_DECIMAL_OF_AT_MOST_SIX_PLACES = re.compile(r"-?\d+(\.\d{1,6})?")
ASSIETTA_POINT_COUNT = 23_295  # the size of the real Strada dell'Assietta recording (D198: the file stays out of git)

A_PLAN = GpxDocument(
    name="Plan run #3",
    description="Casa Marco: Included (1, 4)\nTotals: 212 km",
    waypoints=(
        GpxWaypoint("Casa Marco, Torino (S/E)", Coordinate(45.0703, 7.6869), "Stop 1 and 4 - Included"),
        GpxWaypoint("Briancon", Coordinate(44.8986, 6.6419), "Stop 2 - Included"),
    ),
    tracks=(
        GpxTrack(
            "Leg 1: Casa Marco, Torino -> Briancon",
            (TrackPoint.at(45.0703, 7.6869), TrackPoint.at(44.8986, 6.6419)),
            description="Road to Briancon",
            number=1,
            kind="road",
        ),
        GpxTrack(
            "Strada dell'Assietta",
            (TrackPoint.at(45.056, 7.041, 1650.0), TrackPoint.at(44.958, 6.879, 1530.0)),
            number=3,
            kind="offroad",
        ),
    ),
)


def _read(written: bytes) -> Element:
    root: Element = safe_xml.fromstring(written, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    return root


def _xsd_problems(written: bytes) -> list[str]:
    return [str(error) for error in SCHEMA.iter_errors(written.decode())]


def _points(root: Element) -> list[tuple[str, str, str | None]]:
    return [(point.attrib["lat"], point.attrib["lon"], point.findtext(f"{NS}ele")) for point in root.iter(f"{NS}trkpt")]


def _track_of(*points: TrackPoint) -> GpxDocument:
    return GpxDocument(tracks=(GpxTrack("Trail", points),))


def _as_decimals(points: list[tuple[str, str, str | None]]) -> list[tuple[Decimal, Decimal, Decimal | None]]:
    return [(Decimal(lat), Decimal(lon), None if ele is None else Decimal(ele)) for lat, lon, ele in points]


def _numbers_of(points: list[tuple[str, str, str | None]]) -> list[str]:
    return [number for point in points for number in point if number is not None]


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        yield folder


def test_output_validates_against_gpx_1_1_xsd() -> None:
    written = WRITER.write(A_PLAN)

    assert _xsd_problems(written) == []
    root = _read(written)
    assert (root.attrib["version"], root.attrib["creator"]) == ("1.1", "overland-planner")
    assert [child.tag.removeprefix(NS) for child in root] == ["metadata", "wpt", "wpt", "trk", "trk"]
    assert {element.tag.removeprefix(NS) for element in root.iter()} == {
        "gpx",
        "metadata",
        "name",
        "desc",
        "wpt",
        "trk",
        "number",
        "type",
        "trkseg",
        "trkpt",
        "ele",
    }, "no extensions, no foreign elements, no <time>"


def test_every_field_lands_on_its_adr_010_element() -> None:
    root = _read(WRITER.write(A_PLAN))

    assert [root.findtext(f"{NS}metadata/{NS}{tag}") for tag in ("name", "desc")] == [
        "Plan run #3",
        "Casa Marco: Included (1, 4)\nTotals: 212 km",
    ]
    assert [
        (wpt.findtext(f"{NS}name"), wpt.findtext(f"{NS}desc"), wpt.attrib["lat"], wpt.attrib["lon"])
        for wpt in root.iter(f"{NS}wpt")
    ] == [
        ("Casa Marco, Torino (S/E)", "Stop 1 and 4 - Included", "45.0703", "7.6869"),
        ("Briancon", "Stop 2 - Included", "44.8986", "6.6419"),
    ]
    assert [
        (trk.findtext(f"{NS}name"), trk.findtext(f"{NS}desc"), trk.findtext(f"{NS}number"), trk.findtext(f"{NS}type"))
        for trk in root.iter(f"{NS}trk")
    ] == [
        ("Leg 1: Casa Marco, Torino -> Briancon", "Road to Briancon", "1", "road"),
        ("Strada dell'Assietta", None, "3", "offroad"),
    ]
    assert [len(trk.findall(f"{NS}trkseg")) for trk in root.iter(f"{NS}trk")] == [1, 1]


def test_same_document_gives_same_bytes() -> None:
    assert GpxpyWriter().write(A_PLAN) == GpxpyWriter().write(A_PLAN)


def test_points_come_back_in_order_at_six_decimals() -> None:
    document = _track_of(
        TrackPoint.at(45.0560004, 7.0410006, 1650.5),
        TrackPoint.at(0.000001, -0.00001, 0.00001),  # floats Python prints in scientific notation
        TrackPoint.at(-0.0000004, 0.0000004),  # rounds to zero
        TrackPoint.at(44.958, 6.879, 0.0),  # sea level is an elevation, not a missing one
        TrackPoint.at(45.2, 7.5),  # going back north: never sorted
    )

    written = WRITER.write(document)

    points = _points(_read(written))
    assert _as_decimals(points) == [
        (Decimal("45.056"), Decimal("7.041001"), Decimal("1650.5")),
        (Decimal("0.000001"), Decimal("-0.00001"), Decimal("0.00001")),
        (Decimal("0"), Decimal("0"), None),
        (Decimal("44.958"), Decimal("6.879"), Decimal("0")),
        (Decimal("45.2"), Decimal("7.5"), None),
    ]
    assert all(PLAIN_DECIMAL_OF_AT_MOST_SIX_PLACES.fullmatch(number) for number in _numbers_of(points)), points
    assert _xsd_problems(written) == []


@pytest.mark.parametrize("not_a_number", [math.nan, math.inf, -math.inf])
def test_elevation_that_is_not_a_number_is_left_out(not_a_number: float) -> None:
    written = WRITER.write(_track_of(TrackPoint.at(45.0, 7.0, not_a_number), TrackPoint.at(45.1, 7.1, 1200.0)))

    assert [point[2] for point in _points(_read(written))] == [None, "1200.0"]
    assert _xsd_problems(written) == []


def test_large_track_is_written_whole() -> None:
    # A zigzag, so a writer that sorts or thins cannot pass by accident.
    recorded = [
        (
            round(45.0 + (index * 7919 % 10_000) / 100_000, 6),
            round(7.0 + (index * 104_729 % 10_000) / 100_000, 6),
            1500.0,
        )
        for index in range(ASSIETTA_POINT_COUNT)
    ]

    root = _read(WRITER.write(_track_of(*(TrackPoint.at(*point) for point in recorded))))

    assert [(float(lat), float(lon), float(ele or "nan")) for lat, lon, ele in _points(root)] == recorded


@pytest.mark.parametrize(
    ("given", "written_as"),
    [
        ("Rifugio dell'Alpe", "Rifugio dell'Alpe"),
        ("Bar & Trattoria", "Bar & Trattoria"),
        ("Brianconnais à Névache", "Brianconnais à Névache"),
        ("<b>Fort</b> ]]> &amp;", "<b>Fort</b> ]]> &amp;"),
        ("Col\tde\nla Vanoise", "Col\tde\nla Vanoise"),
        ("Col\x00 de\x01\x08\x0b\x0c\x1f la Vanoise", "Col de la Vanoise"),
        ("Col￾ de￿ la\ud800 Vanoise", "Col de la Vanoise"),
    ],
)
def test_names_stay_well_formed(given: str, written_as: str) -> None:
    document = GpxDocument(
        name=given,
        description=given,
        waypoints=(GpxWaypoint(given, Coordinate(45.0, 7.0), given),),
        tracks=(GpxTrack(given, (TrackPoint.at(45.0, 7.0),), description=given, kind=given),),
    )

    written = WRITER.write(document)

    assert _xsd_problems(written) == []
    root = _read(written)
    assert [element.text or "" for element in root.iter() if element.tag in {f"{NS}{t}" for t in ("name", "desc")}] == [
        written_as
    ] * 6
    assert [element.text or "" for element in root.iter(f"{NS}type")] == [written_as]


@pytest.mark.parametrize("nothing_left", ["", "\x01\x02"])
def test_text_with_nothing_left_is_not_written(nothing_left: str) -> None:
    written = WRITER.write(
        GpxDocument(
            name=nothing_left,
            description="The report",
            waypoints=(GpxWaypoint(nothing_left, Coordinate(45.0, 7.0), nothing_left),),
            tracks=(GpxTrack(nothing_left, (TrackPoint.at(45.0, 7.0),), kind=nothing_left),),
        )
    )

    assert _xsd_problems(written) == []
    root = _read(written)
    assert [element.tag.removeprefix(NS) for element in root.iter()] == [
        "gpx",
        "metadata",
        "desc",
        "wpt",
        "trk",
        "trkseg",
        "trkpt",
    ]


def test_waypoints_come_back_at_six_decimals() -> None:
    document = GpxDocument(
        waypoints=(
            GpxWaypoint("Near the equator", Coordinate(0.000001, -0.00001)),
            GpxWaypoint("Briancon", Coordinate(44.8986004, 6.6419006)),
        )
    )

    written = WRITER.write(document)

    assert _xsd_problems(written) == []
    assert [(Decimal(wpt.attrib["lat"]), Decimal(wpt.attrib["lon"])) for wpt in _read(written).iter(f"{NS}wpt")] == [
        (Decimal("0.000001"), Decimal("-0.00001")),
        (Decimal("44.8986"), Decimal("6.641901")),
    ]


def _readable_text(given: str) -> str:
    """What an XML 1.0 reader can get back: forbidden characters gone, line ends normalised by the reader."""
    kept = "".join(
        character
        for character in given
        if character in "\t\n\r"
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
        or 0x10000 <= ord(character) <= 0x10FFFF
    )
    return kept.replace("\r\n", "\n").replace("\r", "\n")


_ANY_NAME = st.text(alphabet=st.characters(), max_size=24)  # every code point, lone surrogates and controls too
_ALPINE_POINT = st.builds(
    TrackPoint.at,
    st.floats(43.5, 48.0),
    st.floats(5.0, 17.0),
    st.none() | st.floats(-500.0, 5000.0),  # floats near zero are what Python prints in scientific notation
)


# bypass: no state delta - `write` is a pure function of the document with one output, the bytes; the slots a universe
# would declare are the assertions below, compared with the document itself.
@given(name=_ANY_NAME, points=st.lists(_ALPINE_POINT, max_size=12))
@settings(suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_any_name_and_alpine_points_round_trip_in_a_valid_file(name: str, points: list[TrackPoint]) -> None:
    document = GpxDocument(
        name=name,
        waypoints=(GpxWaypoint(name, Coordinate(45.0, 7.0)),),
        tracks=(GpxTrack(name, tuple(points)),),
    )

    written = WRITER.write(document)

    assert _xsd_problems(written) == []
    root = _read(written)
    readable = _readable_text(name)
    assert [element.text for element in root.iter(f"{NS}name")] == ([readable] * 3 if readable else [])
    read_back = _points(root)
    assert all(PLAIN_DECIMAL_OF_AT_MOST_SIX_PLACES.fullmatch(number) for number in _numbers_of(read_back)), read_back
    assert len(read_back) == len(points)
    half_a_place = Decimal("0.0000005")
    for point, (lat, lon, ele) in zip(points, _as_decimals(read_back), strict=True):
        assert abs(lat - Decimal(point.coordinate.latitude)) <= half_a_place
        assert abs(lon - Decimal(point.coordinate.longitude)) <= half_a_place
        assert (ele is None) == (point.elevation_m is None)
        assert ele is None or abs(ele - Decimal(point.elevation_m or 0.0)) <= half_a_place


class _Reordering(GpxpyWriter):
    def write(self, document: GpxDocument) -> bytes:
        return super().write(_with_points(document, lambda points: tuple(reversed(points))))


class _DroppingAPoint(GpxpyWriter):
    def write(self, document: GpxDocument) -> bytes:
        return super().write(_with_points(document, lambda points: points[:-1]))


class _ScientificNotation(GpxpyWriter):
    def write(self, document: GpxDocument) -> bytes:
        return re.sub(rb'lat="[^"]*"', b'lat="1e-05"', super().write(document), count=1)


class _RoundingHard(GpxpyWriter):
    def write(self, document: GpxDocument) -> bytes:
        return re.sub(rb'lat="(-?\d+\.\d)\d*"', rb'lat="\1"', super().write(document))


class _DroppingElevation(GpxpyWriter):
    def write(self, document: GpxDocument) -> bytes:
        return re.sub(rb"<ele>[^<]*</ele>", b"", super().write(document))


class _WithExtensions(GpxpyWriter):
    def write(self, document: GpxDocument) -> bytes:
        return super().write(document).replace(b"</gpx>", b"<extensions/></gpx>")


class _WithMetadataTime(GpxpyWriter):
    def write(self, document: GpxDocument) -> bytes:
        return super().write(document).replace(b"</metadata>", b"<time>2026-11-05T00:00:00Z</time></metadata>")


class _NotXml(GpxpyWriter):
    def write(self, document: GpxDocument) -> bytes:
        return b"not a gpx file"


class _Crashing(GpxpyWriter):
    def write(self, document: GpxDocument) -> bytes:
        raise RuntimeError("the GPX library broke")


class _RenamingTheFirstName(GpxpyWriter):
    def write(self, document: GpxDocument) -> bytes:
        return re.sub(rb"&amp;", b"and", super().write(document), count=1)


def _with_points(
    document: GpxDocument, change: Callable[[tuple[TrackPoint, ...]], tuple[TrackPoint, ...]]
) -> GpxDocument:
    return replace(document, tracks=tuple(replace(track, points=change(track.points)) for track in document.tracks))


def test_healthy_writer_passes_its_probe() -> None:
    assert GpxpyWriter().probe() == ProbeResult(outcome="ok")


@pytest.mark.parametrize(
    ("lying_writer", "reason"),
    [
        (_Reordering, "gpx_writer_points_changed"),
        (_DroppingAPoint, "gpx_writer_points_changed"),
        (_RoundingHard, "gpx_writer_points_changed"),
        (_DroppingElevation, "gpx_writer_points_changed"),
        (_ScientificNotation, "gpx_writer_invalid_number"),
        (_WithExtensions, "gpx_writer_foreign_element"),
        (_WithMetadataTime, "gpx_writer_foreign_element"),
        (_NotXml, "gpx_writer_round_trip_failed"),
        (_Crashing, "gpx_writer_round_trip_failed"),
        (_RenamingTheFirstName, "gpx_writer_names_changed"),
    ],
)
def test_probe_catches_a_writer_that_lies(lying_writer: type[GpxpyWriter], reason: str) -> None:
    assert lying_writer().probe() == ProbeResult(outcome="fatal", reason=reason)


def test_failing_probe_refuses_start(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(app_factory, "GpxpyWriter", _Reordering)

    with pytest.raises(StartupRefusedError) as refused:
        create_app(
            {"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "mock"},
            external=ExternalPorts(clock=FakeClock(), mount_table=FakeMountTable()),
        )

    assert (refused.value.code, refused.value.component) == (1, "gpx_writer")
    lines = list(map(json.loads, capsys.readouterr().out.splitlines()))
    assert [(line["component"], line["reason"]) for line in lines if line["event"] == "health.startup.refused"] == [
        ("gpx_writer", "gpx_writer_points_changed")
    ]
    assert "app.started" not in [line["event"] for line in lines]

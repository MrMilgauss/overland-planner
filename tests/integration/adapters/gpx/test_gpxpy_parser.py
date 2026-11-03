"""`GpxpyParser` on the DISTILL GPX fixtures (brief §6 and §12, ADR-010, US-02a).

Integration level: single examples through the `TrackFileParser` contract on real files; the start-up probe is
checked through `create_app`. The DISTILL import scenarios (03-05/03-07) drive the same parser over HTTP.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from overland_planner.adapters.gpx import gpxpy_parser
from overland_planner.adapters.gpx.gpxpy_parser import GpxpyParser
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.track_file_parser import (
    InvalidTrackFile,
    NoUsableTrack,
    ParsedTrack,
    TrackFileParser,
)
from overland_planner.bootstrap import app_factory
from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from overland_planner.bootstrap.startup import StartupRefusedError
from overland_planner.domain.catalog.track import TrackPoint
from tests.common.fakes import FakeClock, FakeMountTable
from tests.common.workspace import workspace_data_dir

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES = REPO_ROOT / "tests" / "acceptance" / "overland_route_planner_mvp" / "fixtures" / "gpx"
PARSER: TrackFileParser = GpxpyParser()


def _parse(fixture: str) -> object:
    return PARSER.parse((FIXTURES / fixture).read_bytes(), fixture)


def _gpx(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">{body}</gpx>'
    ).encode()


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        yield folder


def test_renamed_text_file_is_invalid() -> None:
    assert isinstance(outcome := _parse("notes.gpx"), InvalidTrackFile)
    assert outcome.file_name == "notes.gpx"


def test_empty_file_is_invalid() -> None:
    assert isinstance(_parse("empty.gpx"), InvalidTrackFile)


def test_external_entity_file_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    def gpxpy_must_not_run(*_: object, **__: object) -> None:
        raise AssertionError("gpxpy parsed a file the pre-parse should have refused")

    monkeypatch.setattr(gpxpy_parser.gpxpy, "parse", gpxpy_must_not_run)

    assert isinstance(_parse("trap.gpx"), InvalidTrackFile)


def test_malformed_coordinates_are_invalid() -> None:
    malformed = _gpx('<trk><trkseg><trkpt lat="north" lon="7.0"/><trkpt lat="45.0" lon="7.1"/></trkseg></trk>')
    out_of_range = _gpx('<trk><trkseg><trkpt lat="95.0" lon="7.0"/><trkpt lat="45.0" lon="7.1"/></trkseg></trk>')

    outcomes = [PARSER.parse(content, "bad.gpx") for content in (malformed, out_of_range)]

    assert all(isinstance(outcome, InvalidTrackFile) for outcome in outcomes), outcomes


def test_waypoints_only_file_has_no_usable_track() -> None:
    assert _parse("waypoints-only.gpx") == NoUsableTrack("waypoints-only.gpx")


def test_tracks_with_fewer_than_two_points_in_total_are_no_usable_track() -> None:
    lonely = _gpx('<trk><name>One</name><trkseg><trkpt lat="45.0" lon="7.0"/></trkseg></trk><trk><trkseg/></trk>')

    assert PARSER.parse(lonely, "lonely.gpx") == NoUsableTrack("lonely.gpx")


def test_assietta_yields_first_usable_track() -> None:
    outcome = _parse("assietta.gpx")

    assert isinstance(outcome, ParsedTrack)
    assert (outcome.name, outcome.description) == ("Strada dell'Assietta", None)
    assert (len(outcome.points), outcome.points[0], outcome.points[-1]) == (
        601,  # every <trkpt> of the fixture's single segment, Pian dell'Alpe first, Sestriere last (HC-1)
        TrackPoint.at(45.056, 7.041, 1650.0),
        TrackPoint.at(44.958, 6.879, 1530.0),
    )


def test_first_usable_track_wins_and_is_named_after_the_file_when_unnamed() -> None:
    content = _gpx(
        '<trk><name>Too short</name><trkseg><trkpt lat="44.0" lon="6.0"/></trkseg></trk>'
        '<trk><desc>Colle delle Finestre</desc><trkseg><trkpt lat="45.1" lon="7.0"/></trkseg>'
        '<trkseg><trkpt lat="45.2" lon="7.1"/><trkpt lat="45.3" lon="7.2" /></trkseg></trk>'
        '<trk><name>Later</name><trkseg><trkpt lat="46.0" lon="8.0"/><trkpt lat="46.1" lon="8.1"/></trkseg></trk>'
    )

    assert PARSER.parse(content, "finestre.gpx") == ParsedTrack(
        name="finestre",
        description="Colle delle Finestre",
        points=(TrackPoint.at(45.2, 7.1), TrackPoint.at(45.3, 7.2)),
    )


def test_probe_rejects_billion_laughs() -> None:
    assert PARSER.probe() == ProbeResult(outcome="ok")
    accepting = GpxpyParser(attack_sample=gpxpy_parser.EMBEDDED_GPX)

    assert accepting.probe() == ProbeResult(outcome="fatal", reason="gpx_parser_accepted_entities")


def test_a_failing_parser_probe_refuses_start_up(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(app_factory, "GpxpyParser", lambda: GpxpyParser(sample=b"not a gpx file"))

    with pytest.raises(StartupRefusedError) as refused:
        create_app(
            {"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "mock"},
            external=ExternalPorts(clock=FakeClock(), mount_table=FakeMountTable()),
        )

    assert (refused.value.code, refused.value.component) == (1, "gpx_parser")
    refusals = [r for r in map(json.loads, capsys.readouterr().out.splitlines()) if r["event"].endswith("refused")]
    assert [(r["component"], r["reason"]) for r in refusals] == [("gpx_parser", "gpx_parser_sample_rejected")]

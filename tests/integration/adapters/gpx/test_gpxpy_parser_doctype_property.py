"""Property: any GPX document with a DOCTYPE inserted is an invalid track file (brief §12, ADR-010)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.adapters.gpx.gpxpy_parser import GpxpyParser
from overland_planner.application.ports.track_file_parser import InvalidTrackFile, ParsedTrack

_names = st.text(alphabet=st.characters(categories=("L", "N"), max_codepoint=0x24F), min_size=1, max_size=12)
_points = st.lists(
    st.tuples(st.floats(-90, 90, allow_nan=False), st.floats(-180, 180, allow_nan=False)), min_size=2, max_size=5
)
_doctypes = st.sampled_from(
    [
        "<!DOCTYPE gpx>",
        '<!DOCTYPE gpx SYSTEM "http://example.invalid/gpx.dtd">',
        '<!DOCTYPE gpx [<!ENTITY x "y">]>',
    ]
)


@given(name=_names, points=_points, doctype=_doctypes)
def test_any_gpx_with_a_doctype_is_an_invalid_file(name: str, points: list[tuple[float, float]], doctype: str) -> None:
    trkpts = "".join(f'<trkpt lat="{lat}" lon="{lon}"/>' for lat, lon in points)
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?>{doctype}'
        f'<gpx version="1.1" creator="pbt" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><name>{name}</name><trkseg>{trkpts}</trkseg></trk></gpx>"
    )
    valid = document.replace(doctype, "")

    assert isinstance(GpxpyParser().parse(valid.encode(), "t.gpx"), ParsedTrack)
    assert isinstance(GpxpyParser().parse(document.encode(), "t.gpx"), InvalidTrackFile)

"""TrackImportService (brief §4, §9, §12; ADR-018; US-02a; D149): uploaded GPX files become track items.

Driving port: `TrackImportService` from the catalog facade (items read back through `ProjectService`). Driven ports:
`CatalogUnitOfWork` and `FileStore` (in-memory doubles in `tests/common/catalog_fakes.py`), `TrackFileParser`
(scripted below: the GPX reading itself is the adapter's integration test), `EventLog` (recording double).
Observable universe = what the driving ports and driven-port boundaries expose: the project list, the open project's
items and revision, the files kept under `files/` and the logged events.
Test Budget: 5 behaviors (import adds one track with its files and event; same bytes keep one original; a refused
file adds nothing; an unknown project adds nothing; files are written before the commit, so a failed write commits
nothing) x 2 = 10; 5 used.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import (
    ProjectNotFoundError,
    ProjectService,
    TrackFile,
    TrackFilesRefusedError,
    TrackImportService,
)
from overland_planner.application.ports.track_file_parser import (
    InvalidTrackFile,
    NoUsableTrack,
    ParsedTrack,
    TrackFileOutcome,
)
from overland_planner.domain.catalog.track import TrackPoint
from tests.common.catalog_fakes import InMemoryCatalog, InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"projects.names", "project.items", "project.revision", "files.originals", "files.tracks", "events"}

POINT = st.builds(
    TrackPoint.at,
    st.floats(-89.0, 89.0),
    st.floats(-179.0, 179.0),
    st.none() | st.floats(-400.0, 4800.0),
)
TRACK = st.builds(
    ParsedTrack,
    name=st.text(min_size=1, max_size=30),
    description=st.none() | st.text(max_size=30),
    points=st.lists(POINT, min_size=2, max_size=25).map(tuple),
)
CONTENT = st.binary(min_size=1, max_size=64)
FILE_NAME = st.from_regex(r"[a-z]{1,8}\.gpx", fullmatch=True)


class ScriptedParser:
    """`TrackFileParser` double: each upload's bytes map to the outcome the test scripted."""

    def __init__(self, outcomes: dict[bytes, TrackFileOutcome]) -> None:
        self._outcomes = outcomes

    def parse(self, content: bytes, file_name: str) -> TrackFileOutcome:
        return self._outcomes[content]

    def probe(self) -> Any:
        raise NotImplementedError


class Planner:
    def __init__(self, outcomes: dict[bytes, TrackFileOutcome], *, failing_files: bool = False) -> None:
        catalog = InMemoryCatalog()
        self.files = InMemoryFileStore(failing=failing_files)
        self.events = RecordingEventLog()
        self.projects = ProjectService(catalog.unit_of_work, FakeClock(datetime(2027, 6, 1, tzinfo=UTC)))
        self.imports = TrackImportService(catalog.unit_of_work, ScriptedParser(outcomes), self.files, self.events)
        self.project_id = self.projects.create("Alpi Occidentali giugno 2027").id

    def view(self) -> dict[str, Any]:
        return {
            "projects.names": tuple(sorted(p.name.value for p in self.projects.list())),
            "project.items": tuple(
                (i.type, i.name, i.included, i.anchor) for i in self.projects.items(self.project_id)
            ),
            "project.revision": self.projects.open(self.project_id).revision,
            "files.originals": tuple(sorted(p for p in self.files.files if p.startswith("originals/"))),
            "files.tracks": tuple(sorted(p for p in self.files.files if p.startswith("tracks/"))),
            "events": tuple((name, fields.get("track_id")) for name, fields in self.events.events),
        }


@given(track=TRACK, content=CONTENT, file_name=FILE_NAME)
def test_an_import_adds_one_included_track_in_recorded_order_with_its_files_kept_and_logged(
    track: ParsedTrack, content: bytes, file_name: str
) -> None:
    planner = Planner({content: track})
    before = planner.view()

    (item,) = planner.imports.import_files(planner.project_id, [TrackFile(file_name, content)])

    sha256 = hashlib.sha256(content).hexdigest()
    canonical_path = f"tracks/{item.id}/canonical.v1.json"
    assert_state_delta(
        before,
        planner.view(),
        UNIVERSE,
        {
            "project.items": gained(("track", track.name, True, None)),
            "project.revision": set_to(before["project.revision"] + 1),
            "files.originals": gained(f"originals/{sha256}.gpx"),
            "files.tracks": gained(canonical_path),
            "events": gained(("import.track", item.id)),
        },
        strict=True,
    )
    assert planner.files.files[f"originals/{sha256}.gpx"] == content
    canonical = planner.files.files[canonical_path]
    recorded = [[p.coordinate.latitude, p.coordinate.longitude, p.elevation_m] for p in track.points]
    assert json.loads(canonical) == {"points": recorded}
    assert item.canonical_sha256 == hashlib.sha256(canonical).hexdigest()
    (listed,) = planner.projects.items(planner.project_id)
    assert (listed.entry, listed.exit) == (track.points[0].coordinate, track.points[-1].coordinate)
    assert (listed.point_count, listed.direction_version, listed.original_sha256) == (len(track.points), 1, sha256)
    assert listed.description == track.description
    assert planner.events.events[-1][1] == {
        "project_id": planner.project_id,
        "track_id": item.id,
        "point_count": len(track.points),
        "length_m": round(listed.length_m, 1),
        "original_sha256": sha256,
    }
    # The path through every recorded point is never shorter than the straight line from entry to exit.
    assert listed.length_m >= listed.entry.great_circle_distance_m(listed.exit) - 1e-6


@given(track=TRACK, content=CONTENT)
def test_importing_the_same_file_twice_keeps_one_original_and_lists_two_tracks(
    track: ParsedTrack, content: bytes
) -> None:
    planner = Planner({content: track})
    planner.imports.import_files(planner.project_id, [TrackFile("first.gpx", content)])
    before = planner.view()

    (again,) = planner.imports.import_files(planner.project_id, [TrackFile("again.gpx", content)])

    assert_state_delta(
        before,
        planner.view(),
        UNIVERSE,
        {
            "project.items": lambda old, new: len(new) == len(old) + 1 and set(new) == set(old),
            "project.revision": set_to(before["project.revision"] + 1),
            "files.tracks": gained(f"tracks/{again.id}/canonical.v1.json"),
            "events": gained(("import.track", again.id)),
        },
        strict=True,
    )


@given(
    track=TRACK,
    refused=st.sampled_from(
        [
            (InvalidTrackFile("notes.gpx", "not XML"), "notes.gpx is not a valid GPX file"),
            (NoUsableTrack("waypoints.gpx"), "waypoints.gpx has no usable track"),
        ]
    ),
)
def test_when_any_file_is_refused_nothing_is_added_and_each_refused_file_is_named(
    track: ParsedTrack, refused: tuple[TrackFileOutcome, str]
) -> None:
    outcome, message = refused
    file_name = message.split(" ", 1)[0]
    planner = Planner({b"good": track, b"bad": outcome})
    before = planner.view()

    with pytest.raises(TrackFilesRefusedError) as raised:
        planner.imports.import_files(planner.project_id, [TrackFile("good.gpx", b"good"), TrackFile(file_name, b"bad")])

    assert raised.value.messages == (message,)
    assert_state_delta(before, planner.view(), UNIVERSE, {}, strict=True)


@given(track=TRACK, content=CONTENT, unknown=st.uuids().map(lambda u: u.hex))
def test_an_import_into_an_unknown_project_is_not_found_and_adds_nothing(
    track: ParsedTrack, content: bytes, unknown: str
) -> None:
    planner = Planner({content: track})
    before = planner.view()

    with pytest.raises(ProjectNotFoundError, match=unknown):
        planner.imports.import_files(unknown, [TrackFile("assietta.gpx", content)])

    assert_state_delta(before, planner.view(), UNIVERSE, {}, strict=True)


@given(track=TRACK, content=CONTENT)
def test_when_the_files_cannot_be_written_the_track_is_not_committed(track: ParsedTrack, content: bytes) -> None:
    planner = Planner({content: track}, failing_files=True)
    before = planner.view()

    with pytest.raises(OSError, match="No space left on device"):
        planner.imports.import_files(planner.project_id, [TrackFile("assietta.gpx", content)])

    assert_state_delta(before, planner.view(), UNIVERSE, {}, strict=True)

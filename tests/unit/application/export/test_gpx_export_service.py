"""Export keeps the trail's stored points in order (US-02b, HC-1, ADR-009 Amendment 2, ADR-010 Amendment 1).

Driving port: `GpxExportService.export`. Driven ports: `PlanningUnitOfWork`, `FileStore`, `GpxWriter` (recording; the
real writer is proven at its own test), `EventLog`.
Observable universe: `plan_runs`, `commits`, `items`, `projects` as planning reads them, `files` as the store holds
them, the `documents` handed to the writer and the `events` logged.
Test Budget: 4 behaviors (each track holds its stored points by the run's version; a track that cannot be proven
refuses with the fixed message; the refusal logs its violation; nothing changes, and an unknown run is not found)
x 2 = 8; 6 used.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import canonical_points_file
from overland_planner.application.export.facade import (
    GpxExportService,
    PlanRunNotFoundError,
    TrackDataInconsistentError,
)
from overland_planner.application.planning.facade import PlanRunQueries
from overland_planner.application.ports.plan_run_repository import NewPlanRun
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.export.gpx_document import GpxDocument
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.application.planning.planning_doubles import InMemoryPlanning

UNIVERSE = {"plan_runs", "commits", "items", "projects", "files", "documents", "events"}
PROJECT = "p"
RUN = "run-1"
REFUSAL = "Track data for this run is inconsistent - recalculate"
VIOLATION = ("invariant.violation", RUN, "HC-5")
VIOLATION_FIELDS = {"plan_run_id", "check", "detail"}
BIG_TRACK_POINTS = 23_295


class _RecordingGpxWriter:
    """Keeps every document it is handed; its bytes are a fingerprint of the document."""

    def __init__(self) -> None:
        self.documents: list[GpxDocument] = []

    def write(self, document: GpxDocument) -> bytes:
        self.documents.append(document)
        return repr(document).encode()

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


@dataclass(frozen=True)
class _StoredTrack:
    """A track of the run. Its item has moved on since: the current version holds the points the other way round."""

    item_id: str
    name: str
    run_version: int
    points: tuple[TrackPoint, ...]

    @property
    def file(self) -> bytes:
        return canonical_points_file(self.points)

    @property
    def later_file(self) -> bytes:
        return canonical_points_file(self.points[::-1])

    def item(self) -> TrackItem:
        return TrackItem(
            id=self.item_id,
            project_id=PROJECT,
            name=self.name,
            description=None,
            original_sha256="original",
            canonical_sha256=_sha256(self.later_file),
            direction_version=self.run_version + 1,
            point_count=len(self.points),
            entry=self.points[-1].coordinate,
            exit=self.points[0].coordinate,
            length_m=1000.0,
        )

    def stop(self) -> PlanStop:
        return replace(
            PlanStop.of(self.item(), 1.0),
            entry=self.points[0].coordinate,
            exit=self.points[-1].coordinate,
            direction_version=self.run_version,
            canonical_sha256=_sha256(self.file),
        )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass
class _Harness:
    """The real service over the doubles of its driven ports, with one stored Ready run: Start, the tracks, End."""

    tracks: tuple[_StoredTrack, ...]
    planning: InMemoryPlanning = field(default_factory=InMemoryPlanning)
    files: InMemoryFileStore = field(default_factory=InMemoryFileStore)
    writer: _RecordingGpxWriter = field(default_factory=_RecordingGpxWriter)
    log: RecordingEventLog = field(default_factory=RecordingEventLog)

    def __post_init__(self) -> None:
        start = PoiItem(id="start", project_id=PROJECT, name="Casa Marco", location=Coordinate(45.0, 7.0))
        self.planning.add_project(
            PROJECT, ProjectSnapshot(start.id, start.id, (start, *(track.item() for track in self.tracks)))
        )
        anchor = PlanStop.of(start, None)
        self.planning.runs.append(
            NewPlanRun(
                id=RUN,
                project_id=PROJECT,
                number=1,
                status="ready",
                failure_reason=None,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                revision=1,
                provider_id="mock",
                objective="distance",
                inputs={},
                stops=(anchor, *(track.stop() for track in self.tracks), replace(anchor, leg_km=1.0)),
            )
        )
        for track in self.tracks:
            self.files.keep_canonical_points(track.item_id, track.run_version, track.file)
            self.files.keep_canonical_points(track.item_id, track.run_version + 1, track.later_file)
        self.service = GpxExportService(PlanRunQueries(self.planning.unit_of_work), self.files, self.writer, self.log)

    def view(self) -> dict[str, Any]:
        snapshot = self.planning.snapshots[PROJECT]
        return {
            "plan_runs": tuple(
                (run.id, run.number, run.status, run.failure_reason, run.stops) for run in self.planning.runs
            ),
            "commits": self.planning.commits,
            "items": snapshot.items,
            "projects": (PROJECT, self.planning.stamps[PROJECT], snapshot.start_item_id, snapshot.end_item_id),
            "files": tuple(sorted(self.files.files.items())),
            "documents": tuple(_tracks_of(document) for document in self.writer.documents),
            "events": tuple(
                (event, fields.get("plan_run_id"), fields.get("check")) for event, fields in self.log.events
            ),
        }

    def replace_track_stop(self, track: _StoredTrack, **changes: Any) -> None:
        run = self.planning.runs[0]
        stops = tuple(replace(stop, **changes) if stop.item_id == track.item_id else stop for stop in run.stops)
        self.planning.runs[0] = replace(run, stops=stops)

    def spoil(self, track: _StoredTrack, spoiled: Callable[[bytes], bytes] | None) -> None:
        """The run's version of the file changes behind the planner's back; `None` makes it vanish."""
        if spoiled is None:
            self.files.lose_canonical_points(track.item_id, track.run_version)
        else:
            self.files.keep_canonical_points(track.item_id, track.run_version, spoiled(track.file))

    def violations(self) -> list[dict[str, object]]:
        return [fields for event, fields in self.log.events if event == "invariant.violation"]


def _tracks_of(document: GpxDocument) -> tuple[tuple[str, tuple[TrackPoint, ...]], ...]:
    return tuple((track.name, track.points) for track in document.tracks)


def _expected(tracks: tuple[_StoredTrack, ...]) -> tuple[tuple[str, tuple[TrackPoint, ...]], ...]:
    return tuple((track.name, track.points) for track in tracks)


def _one_more_document(old: Any, new: Any) -> bool:
    return len(new) == len(old) + 1


_point = st.builds(
    TrackPoint.at,
    st.floats(-90, 90),
    st.floats(-180, 180),
    st.none() | st.floats(-500, 9000),
)
_stored_track = st.builds(
    lambda name, run_version, points: (name, run_version, tuple(points)),
    st.text(min_size=1, max_size=20),
    st.integers(1, 9),
    st.lists(_point, min_size=2, max_size=30),
)
_tracks = st.lists(_stored_track, min_size=1, max_size=4).map(
    lambda rows: tuple(_StoredTrack(f"track-{i}", *row) for i, row in enumerate(rows))
)


def _flip(at: int, mask: int) -> Callable[[bytes], bytes]:
    def _flipped(content: bytes) -> bytes:
        place = at % len(content)
        return content[:place] + bytes([content[place] ^ mask]) + content[place + 1 :]

    return _flipped


def _cut(count: int) -> Callable[[bytes], bytes]:
    return lambda content: content[:-count]


def _add(extra: bytes) -> Callable[[bytes], bytes]:
    return lambda content: content + extra


_spoils = st.one_of(
    st.none(),
    st.builds(_flip, st.integers(0, 100_000), st.integers(1, 255)),
    st.builds(_cut, st.integers(1, 100_000)),
    st.builds(_add, st.binary(min_size=1, max_size=20)),
)


@settings(deadline=None)
@given(tracks=_tracks)
def test_the_document_holds_every_track_with_its_name_and_its_stored_points_in_order(
    tracks: tuple[_StoredTrack, ...],
) -> None:
    harness = _Harness(tracks)
    before = harness.view()

    answer = harness.service.export(RUN)

    assert_state_delta(before, harness.view(), UNIVERSE, {"documents": set_to((_expected(tracks),))}, strict=True)
    assert answer == repr(harness.writer.documents[-1]).encode(), "the answer is the writer's file"


def test_a_full_size_track_exports_whole() -> None:
    # bypass: the size is the input here; one generated sequence proves it, and many would only slow the mutation runs.
    points = tuple(TrackPoint.at(45.0 + i / 1e6, 7.0 + i / 1e6, float(i % 3000)) for i in range(BIG_TRACK_POINTS))
    track = _StoredTrack("assietta", "Strada dell'Assietta", 1, points)
    harness = _Harness((track,))
    before = harness.view()

    harness.service.export(RUN)

    assert_state_delta(before, harness.view(), UNIVERSE, {"documents": set_to((_expected((track,)),))}, strict=True)


@settings(deadline=None)
@given(tracks=_tracks, victim=st.integers(0, 3), spoil=_spoils)
def test_inconsistent_file_refuses_with_the_verbatim_message(
    tracks: tuple[_StoredTrack, ...], victim: int, spoil: Callable[[bytes], bytes] | None
) -> None:
    harness = _Harness(tracks)
    harness.spoil(tracks[victim % len(tracks)], spoil)
    before = harness.view()

    with pytest.raises(TrackDataInconsistentError) as refusal:
        harness.service.export(RUN)

    assert str(refusal.value) == REFUSAL
    assert_state_delta(before, harness.view(), UNIVERSE, {"events": gained(VIOLATION)}, strict=True)


@settings(deadline=None)
@given(tracks=_tracks, victim=st.integers(0, 3), spoil=_spoils)
def test_inconsistent_file_logs_invariant_violation(
    tracks: tuple[_StoredTrack, ...], victim: int, spoil: Callable[[bytes], bytes] | None
) -> None:
    harness = _Harness(tracks)
    track = tracks[victim % len(tracks)]
    harness.spoil(track, spoil)

    with pytest.raises(TrackDataInconsistentError):
        harness.service.export(RUN)

    assert len(harness.violations()) == 1
    violation = harness.violations()[0]
    assert set(violation) == VIOLATION_FIELDS
    assert (violation["plan_run_id"], violation["check"]) == (RUN, "HC-5")
    assert f"track {track.item_id}: canonical file v{track.run_version}" in str(violation["detail"])


# bypass: two fixed shapes of a broken stored run; there is no input to vary, the bytes above already vary.
@pytest.mark.parametrize(
    ("broken_by", "detail"),
    [("unreadable_file_with_its_own_hash", "canonical file v1"), ("stop_without_a_version", "no direction version")],
)
def test_a_track_that_cannot_be_read_by_the_run_refuses_the_same_way(broken_by: str, detail: str) -> None:
    track = _StoredTrack("assietta", "Strada dell'Assietta", 1, (TrackPoint.at(45.0, 7.0), TrackPoint.at(45.1, 7.1)))
    harness = _Harness((track,))
    if broken_by == "stop_without_a_version":
        harness.replace_track_stop(track, direction_version=None)
    else:
        harness.files.keep_canonical_points(track.item_id, track.run_version, b"not json")
        harness.replace_track_stop(track, canonical_sha256=_sha256(b"not json"))
    before = harness.view()

    with pytest.raises(TrackDataInconsistentError) as refusal:
        harness.service.export(RUN)

    assert str(refusal.value) == REFUSAL
    assert_state_delta(before, harness.view(), UNIVERSE, {"events": gained(VIOLATION)}, strict=True)
    assert detail in str(harness.violations()[0]["detail"])


@settings(deadline=None)
@given(tracks=_tracks, unknown=st.text(max_size=40).filter(lambda run_id: run_id != RUN))
def test_export_changes_nothing_and_unknown_run_is_not_found(tracks: tuple[_StoredTrack, ...], unknown: str) -> None:
    harness = _Harness(tracks)
    before = harness.view()

    with pytest.raises(PlanRunNotFoundError):
        harness.service.export(unknown)

    assert_state_delta(before, harness.view(), UNIVERSE, {}, strict=True)

    harness.service.export(RUN)

    assert_state_delta(before, harness.view(), UNIVERSE, {"documents": _one_more_document}, strict=True)

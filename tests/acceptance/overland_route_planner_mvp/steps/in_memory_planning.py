"""Layer 1-2 composition for the slice 02 `@property` scenarios (D192, Mandate 9) and their generated projects.

Driving port: `PlanRequestJob.run` from the planning facade, the work one Calculate starts (snapshot, legs, solve,
guard, store), read back through `PlanRunQueries.get`, the read side the plan-run endpoints use. Driven ports, wired
like the production composition root but in memory: `InMemoryPlanning` (the database), `InMemoryFileStore` (the
canonical track files the import wrote), the production offline road map (`MockRoutingProvider`, straight line x 1.3)
behind `LegResolver`, `FakeClock`, `RecordingEventLog`, and the `TourSolver` port served by
`InProcessOrToolsTourSolver`: the solver child's own OR-Tools solve hosted in the test process (D192 leaves the
hosting to DELIVER; D215 sets the budget of the HC-1, HC-5 and A-2 properties to `solution_limit` 100, D216 keeps the
default budget for A-6). No HTTP and no SQLite here: the HTTP path is covered by the example scenarios at layer 3.

What the in-memory doubles cannot model: SQLite transactions and the single-writer lock across processes, files that
change between the snapshot and the guard (covered by the guard's unit tests), and the solver child's process
lifecycle (covered by `@solver_child` scenarios and `tests/integration/adapters/solver`).

Generated projects (D192): POIs and tracks in the Alpine box lat 44.0-46.5, lon 6.5-8.5; the item count includes the
anchors; a round trip has one S/E place, a one-way trip a Start and an End; tracks run entry -> exit in recorded order,
some are loops, some share a point with another item (zero-length legs); a few Excluded items are listed too. Readable
pinned cases are built from the trail files and named places of the example scenarios (`@example`, D188).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import defusedxml.ElementTree as SafeXml
from hypothesis import strategies as st

from overland_planner.adapters.routing.mock_routing_provider import MockRoutingProvider
from overland_planner.application.catalog.facade import (
    canonical_file_sha256,
    canonical_points_file,
    parse_canonical_points_file,
    reversed_points_sha256,
)
from overland_planner.application.planning.facade import PlanRequestJob, PlanRunQueries
from overland_planner.application.ports.plan_run_repository import PlanRunDetail
from overland_planner.application.ports.project_snapshot_reader import ProjectStamp
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.catalog.track import TrackPoint
from overland_planner.domain.planning.invariant_guard import CanonicalFileEvidence, InvariantGuard
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder
from tests.acceptance.overland_route_planner_mvp.steps.places import PLACES, trail_file_bytes
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.predicates import gained
from tests.common.solver_fakes import InProcessOrToolsTourSolver
from tests.common.state_delta import assert_state_delta
from tests.unit.application.planning.planning_doubles import InMemoryPlanning

PROJECT = "generated-project"
STAMP = ProjectStamp(revision=1, objective="distance")
LATITUDES = (44.0, 46.5)
LONGITUDES = (6.5, 8.5)
GPX_NS = "{http://www.topografix.com/GPX/1/1}"
# What the composition shows (Mandate 8): the project's plan runs (number, status, reason), and the guard's runtime
# event of K2 (`invariant.violation`, kpi-contracts.yaml), which must stay at zero.
UNIVERSE = {"project.plan_runs", "log.invariant_violations"}


# ------------------------------------------------------------------------------------------- generated projects
@dataclass(frozen=True)
class GeneratedProject:
    """A project as planning reads it, plus the canonical files its import stored: (track id, version, bytes)."""

    snapshot: ProjectSnapshot
    files: tuple[tuple[str, int, bytes], ...]
    label: str = "generated"

    def __repr__(self) -> str:  # Hypothesis prints falsifying examples; the files are noise there
        items = ", ".join(_item_repr(item) for item in self.snapshot.items)
        anchors = f"start={self.snapshot.start_item_id}, end={self.snapshot.end_item_id}"
        return f"GeneratedProject({self.label}: {anchors}, [{items}])"

    def _repr_pretty_(self, printer: Any, cycle: bool) -> None:  # how Hypothesis prints a falsifying example
        printer.text(repr(self))

    def road_map_provider(self) -> MockRoutingProvider:
        """The offline road map this project is planned on: straight line x 1.3 unless a project overrides it."""
        return MockRoutingProvider()

    def tracks_to_drive(self) -> tuple[TrackItem, ...]:
        return tuple(item for item in self.snapshot.visited_items() if isinstance(item, TrackItem))

    def stored_points(self, track: TrackItem) -> tuple[TrackPoint, ...]:
        content = next(c for track_id, v, c in self.files if (track_id, v) == (track.id, track.direction_version))
        return parse_canonical_points_file(content)

    def evidence(self) -> dict[str, CanonicalFileEvidence]:
        """What the guard is shown of each stored file, computed here from the bytes (the test's own reading), with the
        hash of its points reversed by the production function, so a retrace goes through the same guard rule."""
        found = {}
        for track_id, _version, content in self.files:
            points = parse_canonical_points_file(content)
            first, last = points[0].coordinate, points[-1].coordinate
            sha256, reversed_sha256 = canonical_file_sha256(content), reversed_points_sha256(points)
            found[track_id] = CanonicalFileEvidence(sha256, len(points), first, last, reversed_sha256)
        return found


def _item_repr(item: CatalogItem) -> str:
    excluded = "" if item.included else " excluded"
    if isinstance(item, TrackItem):
        return f"{item.id} track {_point(item.entry)}->{_point(item.exit)} {item.point_count}pts{excluded}"
    return f"{item.id} poi {_point(item.location)}{excluded}"


def _point(coordinate: Coordinate) -> str:
    return f"({coordinate.latitude:.4f}, {coordinate.longitude:.4f})"


def _coordinate(lat: float, lon: float) -> Coordinate:
    return Coordinate(round(lat, 6), round(lon, 6))


def track_item(
    item_id: str, name: str, points: tuple[TrackPoint, ...], version: int = 1, included: bool = True
) -> tuple[TrackItem, bytes]:
    canonical = canonical_points_file(points)
    length_m = sum(a.coordinate.great_circle_distance_m(b.coordinate) for a, b in pairwise(points))
    item = TrackItem(
        id=item_id,
        project_id=PROJECT,
        name=name,
        description=None,
        original_sha256=f"original-of-{item_id}",
        canonical_sha256=canonical_file_sha256(canonical),
        direction_version=version,
        point_count=len(points),
        entry=points[0].coordinate,
        exit=points[-1].coordinate,
        length_m=length_m,
        included=included,
    )
    return item, canonical


def poi_item(item_id: str, name: str, location: Coordinate, included: bool = True) -> PoiItem:
    return PoiItem(id=item_id, project_id=PROJECT, name=name, location=location, included=included)


def assembled(
    start: PoiItem, end: PoiItem, others: list[tuple[CatalogItem, bytes | None]], label: str
) -> GeneratedProject:
    listed = {start.id: start, end.id: end} | {item.id: item for item, _ in others}
    files = tuple(
        (item.id, item.direction_version, content)
        for item, content in others
        if isinstance(item, TrackItem) and content is not None
    )
    return GeneratedProject(ProjectSnapshot(start.id, end.id, tuple(listed.values())), files, label)


@st.composite
def _generated(draw: st.DrawFn, low: int, high: int) -> GeneratedProject:
    used: list[Coordinate] = []

    def point() -> Coordinate:
        if used and draw(st.integers(0, 5), label="share a point") == 0:
            return draw(st.sampled_from(used), label="shared point")
        lat = draw(st.floats(*LATITUDES, allow_nan=False), label="lat")
        lon = draw(st.floats(*LONGITUDES, allow_nan=False), label="lon")
        fresh = _coordinate(lat, lon)
        used.append(fresh)
        return fresh

    def track(item_id: str, included: bool) -> tuple[TrackItem, bytes]:
        entry = point()
        exit_ = entry if draw(st.integers(0, 7), label="loop") == 0 else point()
        between = [TrackPoint(point()) for _ in range(draw(st.integers(0, 4), label="points between"))]
        points = (TrackPoint(entry), *between, TrackPoint(exit_))
        return track_item(item_id, f"Track {item_id}", points, draw(st.integers(1, 3)), included)

    def item(item_id: str, included: bool = True) -> tuple[CatalogItem, bytes | None]:
        if draw(st.booleans(), label="track or place"):
            return track(item_id, included)
        return poi_item(item_id, f"Place {item_id}", point(), included), None

    included_count = draw(st.integers(low, high), label="included items")
    round_trip = draw(st.booleans(), label="round trip")
    start = poi_item("start", "Start place", point())
    end = start if round_trip else poi_item("end", "End place", point())
    others = [item(f"item-{i}") for i in range(included_count - (1 if round_trip else 2))]
    others += [item(f"excluded-{i}", included=False) for i in range(draw(st.integers(0, 2), label="excluded"))]
    order = draw(st.permutations(range(len(others))), label="list order")
    return assembled(start, end, [others[i] for i in order], "round trip" if round_trip else "one-way")


def generated_projects(low: int, high: int) -> st.SearchStrategy[GeneratedProject]:
    return _generated(low, high)


# --------------------------------------------------------------------------- pinned, readable cases (@example)
def _fixture_points(file_name: str) -> tuple[TrackPoint, ...]:
    root = SafeXml.fromstring(trail_file_bytes(file_name))
    return tuple(TrackPoint.at(float(p.attrib["lat"]), float(p.attrib["lon"])) for p in root.iter(f"{GPX_NS}trkpt"))


def _place(item_id: str, name: str) -> PoiItem:
    place = PLACES[name]
    return poi_item(item_id, name, Coordinate(place.lat, place.lon))


def assietta_reversing_would_be_shorter() -> GeneratedProject:
    """A-1 / US-03 S1: Start at the Assietta's exit (Sestriere), End at its entry (Pian dell'Alpe)."""
    assietta = track_item("assietta", "Strada dell'Assietta", _fixture_points("assietta.gpx"))
    start, end = _place("start", "Hotel Sestriere"), _place("end", "Rifugio Pian dell'Alpe")
    return assembled(start, end, [assietta], "A-1 Assietta, one-way Sestriere -> Pian dell'Alpe")


def day_trip_with_a_loop() -> GeneratedProject:
    """The Assietta, the Jafferau loop and Briancon, round trip from Casa Marco (US-03 S4, US-02b)."""
    home = _place("home", "Casa Marco, Torino")
    others: list[tuple[CatalogItem, bytes | None]] = [
        track_item("assietta", "Strada dell'Assietta", _fixture_points("assietta.gpx")),
        track_item("jafferau", "Jafferau loop", _fixture_points("jafferau-loop.gpx")),
        (_place("briancon", "Briancon"), None),
    ]
    return assembled(home, home, others, "day trip with the Jafferau loop, round trip from Casa Marco")


def seeded_project(items: int, seed: int, start_name: str, end_name: str) -> GeneratedProject:
    """US-04 S1's readable seeds (D188): `items` Included items in all, the anchors among them, drawn with `seed`."""
    draw = random.Random(seed)  # noqa: S311 - a readable seed, not a secret
    start = _place("start", start_name)
    end = start if end_name == start_name else _place("end", end_name)
    others: list[tuple[CatalogItem, bytes | None]] = []
    for i in range(items - (1 if start is end else 2)):
        a = _coordinate(draw.uniform(*LATITUDES), draw.uniform(*LONGITUDES))
        if draw.random() < 0.5:
            others.append((poi_item(f"item-{i}", f"Place {i}", a), None))
            continue
        b = _coordinate(draw.uniform(*LATITUDES), draw.uniform(*LONGITUDES))
        others.append(track_item(f"item-{i}", f"Track {i}", (TrackPoint(a), TrackPoint(b))))
    return assembled(start, end, others, f"{items} items, seed {seed}, {start_name} -> {end_name}")


# ------------------------------------------------------------------------------------------------ composition
class _Progress:
    """The registry's side of a job (`PlanJobProgress`): one job, the solver slot always free."""

    def enter(self, state: str) -> None:
        pass

    def note(self, **facts: object) -> None:
        pass

    @contextmanager
    def solver_slot(self) -> Iterator[None]:
        yield


@dataclass(frozen=True)
class GeneratedPlan:
    project: GeneratedProject
    detail: PlanRunDetail

    @property
    def stops(self) -> tuple[PlanStop, ...]:
        return self.detail.stops


class InMemoryComposition:
    """One planner, in memory, holding one generated project and nothing planned yet ("from scratch")."""

    def __init__(self, project: GeneratedProject, budget: int) -> None:
        self.planning = InMemoryPlanning()
        self.planning.add_project(PROJECT, project.snapshot, STAMP)
        self.files = InMemoryFileStore()
        for track_id, version, content in project.files:
            self.files.keep_canonical_points(track_id, version, content)
        self.log = RecordingEventLog()
        self.job = PlanRequestJob(
            unit_of_work=self.planning.unit_of_work,
            legs=LegResolver(project.road_map_provider()),
            solver=InProcessOrToolsTourSolver(),
            budget=budget,
            clock=FakeClock(),
            event_log=self.log,
            files=self.files,
        )
        self.runs = PlanRunQueries(self.planning.unit_of_work)
        self.project = project

    def capture_universe(self) -> dict[str, Any]:
        rows = tuple((run.number, run.status, self._reason(run.id)) for run in self.runs.list(PROJECT))
        return {"project.plan_runs": rows, "log.invariant_violations": len(self.log.fields_of("invariant.violation"))}

    def calculate(self) -> GeneratedPlan:
        """Marco presses Calculate once; the plan must be stored ready and the guard must have found nothing."""
        before = self.capture_universe()
        stored = self.job.run(PROJECT, _Progress())
        after = self.capture_universe()
        assert_state_delta(before, after, UNIVERSE, {"project.plan_runs": gained((1, "ready", None))})
        detail = self.runs.get(stored.plan_run_id)
        assert detail is not None, "the stored plan run cannot be opened"
        return GeneratedPlan(self.project, detail)

    def _reason(self, plan_run_id: str) -> str | None:
        detail = self.runs.get(plan_run_id)
        return None if detail is None else detail.failure_reason


def plan_from_scratch(
    budget: int, cache: dict[GeneratedProject, GeneratedPlan]
) -> Callable[[GeneratedProject], GeneratedPlan]:
    """Each project planned once in a fresh composition; several Thens of one scenario share the plans (same seed)."""

    def plan(project: GeneratedProject) -> GeneratedPlan:
        if project not in cache:
            cache[project] = InMemoryComposition(project, budget).calculate()
        return cache[project]

    return plan


def guard_finds_nothing(plan: GeneratedPlan) -> None:
    """ADR-009's guard as the oracle, run again here on what was stored, against the test's own reading of the files."""
    snapshot = plan.project.snapshot
    builder, resolver = SolverModelBuilder(snapshot), LegResolver(plan.project.road_map_provider())
    legs = resolver.resolve(builder.required_pairs())
    second = builder.retrace_pairs(legs)  # the retrace pairs, as the job asks them (ADR-017 section 2)
    legs = legs.merged_with(resolver.resolve(second)) if second else legs
    violation = InvariantGuard(snapshot, legs).check_plan(plan.stops, plan.project.evidence())
    assert violation is None, f"the stored plan breaks {violation.check}: {violation.detail}"

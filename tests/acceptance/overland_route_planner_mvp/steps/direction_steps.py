"""Slice 02 steps: direction-safe plans, fixed Start and End, honest totals (US-03, US-04, US-05).

Example scenarios run at layer 3 through the driving ports (D115): the HTTP API of the in-process planner built by the
production composition root, a real planner server for the `@ui @phone` scenario, waiver W1 for the guard scenario.
Every Calculate, removal and setting captures the universe before and after (Mandate 8). `@property` scenarios run at
layer 1-2 through `in_memory_planning.InMemoryComposition` (D192), Hypothesis-driven from the Then, so a failure shrinks
to a small project; the Thens of one scenario share each project's plan (same seed).

Proposed shapes DELIVER fills (DISTILL's proposal, as in slice 01b; only what the scenarios read):
- plan run (`GET /api/plan-runs/{id}`): `totals {road_km, road_s, offroad_km, offroad_s, total_km, total_s}`; each stop
  `cumulative_km`, and for a track `track_km`, `offroad_s`; a Failed run's `report {reason}` in product words (D206).
- plan runs list: `stale` per run (brief section 8: project revision != the run's revision).
- project (`GET|PATCH /api/projects/{id}`): `offroad_speed_kmh`, default 15; 0 or less is a 422 `validation_error`.
- items (`GET .../items?type=poi`): the Start/End choices; `DELETE .../items/{item_id}` removes an item and clears the
  anchor it held; `PUT .../anchors` accepts `null` for an anchor that stays unset.
- the offline road map reads `MOCK_PLAN` (brief section 12): per-pair distance and road time, `fixtures/road-maps/`.
Durations are shown as "9h40": seconds rounded to the nearest minute.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from hypothesis import HealthCheck, example, given, seed, settings
from pytest_bdd import given as given_step
from pytest_bdd import parsers, then, when

from overland_planner.bootstrap.settings import Settings
from overland_planner.domain.catalog.item import TrackItem
from tests.acceptance.overland_route_planner_mvp.steps.browser import REPO_ROOT, PhoneItineraryJourney, PhoneView
from tests.acceptance.overland_route_planner_mvp.steps.catalog_steps import (
    add_poi,
    assert_track_from_to,
    require_success,
    set_anchors,
)
from tests.acceptance.overland_route_planner_mvp.steps.in_memory_planning import (
    GeneratedPlan,
    GeneratedProject,
    InMemoryComposition,
    assietta_reversing_would_be_shorter,
    day_trip_with_a_loop,
    generated_projects,
    guard_finds_nothing,
    plan_from_scratch,
    seeded_project,
)
from tests.acceptance.overland_route_planner_mvp.steps.places import (
    ENTRY_EXIT_TOLERANCE_M,
    PLACES,
    ROAD_MAPS,
    distance_m,
    trail_file_bytes,
)
from tests.acceptance.overland_route_planner_mvp.steps.plan_steps import (
    ASSIETTA,
    BRIANCON,
    FIRST_TRIP,
    HOME,
    TRACK_FILE_OF,
    assert_driven_from_to,
    assert_first_plan_was_added,
    calculate_a_plan,
    ensure_item,
    ensure_project,
    expected_road_km,
    export_the_plan,
    exported_file,
    gpx_tracks,
    prepare_day_trip,
    press_calculate,
    stop_named,
    stops,
    wait_for_plan,
)
from tests.acceptance.overland_route_planner_mvp.steps.planner import ServerPlanner
from tests.acceptance.overland_route_planner_mvp.steps.world import (
    CATALOG_UNIVERSE,
    PLANNING_UNIVERSE,
    PlannerWorld,
)
from tests.common.predicates import gained
from tests.common.solver_fakes import RuleBreakingTourSolver
from tests.common.state_delta import assert_state_delta

COORD = r"-?\d+(?:\.\d+)?"
DURATION = r"\d+h\d\d"
JAFFERAU = "Jafferau loop"
MAIRA_VARAITA = "Maira-Varaita ridge"
AOSTA = "Aosta"
DOLOMITI = "Dolomiti 2028"
DOLOMITI_PLACES = ("Passo Giau", "Passo Falzarego", "Rifugio Auronzo", "Misurina", "Passo Valparola")
PLAN_RUN_4_ROAD_MAP = ROAD_MAPS / "plan-run-4.yaml"
PROPERTY_BUDGET = 100  # D215: solution_limit 100 for the HC-1, HC-5 and A-2 properties
DEFAULT_SEARCH_BUDGET = int(Settings.model_fields["solver_budget"].default)  # D216: 10,000, as in production
KM_TOLERANCE = 0.05
HEALTH_CHECKS = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.large_base_example]


# ----------------------------------------------------------------------------------------------- helpers
def hours_minutes(seconds: float) -> str:
    """How the planner shows a duration: "2h17", to the nearest minute."""
    minutes = round(seconds / 60)
    return f"{minutes // 60}h{minutes % 60:02d}"


def runs_by_number(world: PlannerWorld) -> dict[int, dict[str, Any]]:
    assert world.project_id is not None, "no project is open"
    answer = world.marco().plan_runs(world.project_id)
    assert answer.status_code == 200, f"the plan runs did not open: {answer.status_code} {answer.text[:300]}"
    return {int(run["number"]): dict(run) for run in answer.json()}


def plan_run_detail(world: PlannerWorld, number: int) -> dict[str, Any]:
    runs = runs_by_number(world)
    assert number in runs, f"there is no plan run #{number}: {sorted(runs)}"
    answer = world.marco().plan_run(str(runs[number]["id"]))
    assert answer.status_code == 200, f"plan run #{number} did not open: {answer.status_code} {answer.text[:300]}"
    return dict(answer.json())


def totals_of(detail: dict[str, Any]) -> dict[str, Any]:
    totals = detail.get("totals")
    assert totals, f"plan run #{detail.get('number')} shows no totals (it shows {sorted(detail)})"
    return dict(totals)


def opened(world: PlannerWorld) -> dict[str, Any]:
    detail = world.scratch.get("opened_run")
    assert detail is not None, "no plan run was opened"
    return dict(detail)


def assert_km(shown: Any, km: float, what: str) -> None:
    assert isinstance(shown, int | float), f"{what} shows no distance: {shown!r}"
    assert abs(shown - km) <= KM_TOLERANCE, f"{what} is {shown} km, not {km} km"


def item_id_of(world: PlannerWorld, name: str) -> str:
    return str(world.item_named(name)["id"])


def remove_item(world: PlannerWorld, name: str) -> None:
    """Marco confirms the removal of an item: the dialog's single action (D188)."""
    assert world.project_id is not None, "no project is open"
    item_id = item_id_of(world, name)
    world.before = world.planning_view()
    world.note(world.marco().remove_item(world.project_id, item_id))
    world.after = world.planning_view()


def project_view(world: PlannerWorld) -> dict[str, Any]:
    assert world.project_id is not None, "no project is open"
    answer = world.marco().project(world.project_id)
    assert answer.status_code == 200, f"the project did not open: {answer.status_code} {answer.text[:300]}"
    return {**world.catalog_view(), "project.offroad_speed_kmh": answer.json().get("offroad_speed_kmh")}


def set_offroad_speed(world: PlannerWorld, speed: float) -> None:
    assert world.project_id is not None, "no project is open"
    world.before = project_view(world)
    world.note(world.marco().update_project(world.project_id, offroad_speed_kmh=speed))
    world.after = project_view(world)


def compute_plan_run_4(world: PlannerWorld) -> None:
    """Plan run #4 of the first trip on the scripted road map: Casa Marco round trip over the three tracks."""
    world.environ["MOCK_PLAN"] = str(PLAN_RUN_4_ROAD_MAP)  # read when the planner starts (brief section 12)
    ensure_project(world, FIRST_TRIP)
    for name in (ASSIETTA, JAFFERAU, MAIRA_VARAITA, HOME):
        ensure_item(world, name)
    set_anchors(world, HOME, HOME)
    require_success(world, "set home as Start and End")
    for _ in range(4):
        calculate_a_plan(world)
    assert max(runs_by_number(world)) == 4, f"plan runs: {sorted(runs_by_number(world))}"


def itinerary_rows(detail: dict[str, Any]) -> list[dict[str, Any]]:
    return list(detail["stops"])


# ------------------------------------------------------------------------- US-03: the Assietta's direction
@given_step(
    parsers.re(
        rf'track "(?P<track>[^"]+)" runs from (?P<entry>[^(]+) \((?P<elat>{COORD}), (?P<elon>{COORD})\) '
        rf"to (?P<exit>[^(]+) \((?P<xlat>{COORD}), (?P<xlon>{COORD})\)"
    ),
    converters={"elat": float, "elon": float, "xlat": float, "xlon": float},
)
def given_track_runs_from_to(
    world: PlannerWorld, track: str, entry: str, elat: float, elon: float, exit: str, xlat: float, xlon: float
) -> None:
    for place, lat, lon in ((entry, elat, elon), (exit, xlat, xlon)):
        assert (PLACES[place].lat, PLACES[place].lon) == (lat, lon), f"{place} is not at {lat}, {lon} in the tests"
    ensure_project(world, FIRST_TRIP)
    ensure_item(world, track)
    assert_track_from_to(world, track, entry, exit)


@given_step(
    parsers.re(rf'Start is "(?P<name>[^"]+)" at (?P<lat>{COORD}), (?P<lon>{COORD})'),
    converters={"lat": float, "lon": float},
)
def given_start_is_at(world: PlannerWorld, name: str, lat: float, lon: float) -> None:
    add_poi(world, name, lat, lon)
    require_success(world, f"add {name!r}")
    world.scratch["start_name"] = name


@given_step(
    parsers.re(rf'End is "(?P<name>[^"]+)" at (?P<lat>{COORD}), (?P<lon>{COORD})'),
    converters={"lat": float, "lon": float},
)
def given_end_is_at(world: PlannerWorld, name: str, lat: float, lon: float) -> None:
    add_poi(world, name, lat, lon)
    require_success(world, f"add {name!r}")
    set_anchors(world, world.scratch["start_name"], name)
    require_success(world, f"set {world.scratch['start_name']!r} as Start and {name!r} as End")


@then(parsers.re(r'the itinerary row reads "(?P<track>[^"]+?)  (?P<entry>[^"]+) -> (?P<exit>[^"]+)"'))
def then_the_itinerary_row_reads(world: PlannerWorld, track: str, entry: str, exit: str) -> None:
    assert_first_plan_was_added(world)
    assert_driven_from_to(world, track, entry, exit)  # the row's places are checked by coordinates (D109)


@then(
    parsers.re(
        r"the plan has about (?P<total>\d+\.\d) km of road \(two legs of about (?P<leg>\d+\.\d) km on the offline "
        r"road map\) although a reversed trail would need none"
    ),
    converters={"total": float, "leg": float},
)
def then_the_plan_has_about_km_of_road(world: PlannerWorld, total: float, leg: float) -> None:
    legs = [stop["leg_km"] for stop in stops(world) if stop["leg_km"] is not None]
    assert len(legs) == 2, f"the plan has {len(legs)} road legs: {legs}"
    for shown in legs:
        assert abs(shown - leg) <= 0.1, f"a road leg is {shown} km, not about {leg} km"
    assert abs(sum(legs) - total) <= 0.1, f"the plan has {sum(legs):.1f} km of road, not about {total} km"
    trail = world.item_named(ASSIETTA)
    start, end = (world.item_named(name)["location"] for name in (world.scratch["start_name"], end_place_name(world)))
    for place, point in ((start, trail["exit"]), (end, trail["entry"])):  # driven exit -> entry: 0 km of road
        gap = distance_m(place["lat"], place["lon"], point["lat"], point["lon"])
        assert gap <= ENTRY_EXIT_TOLERANCE_M, f"a reversed trail would still need {gap:.0f} m of road here"


def end_place_name(world: PlannerWorld) -> str:
    """The End of the open trip, by name (the item list shows the anchor)."""
    ends = [item["name"] for item in world.items() if item.get("anchor") in ("end", "start_end")]
    assert len(ends) == 1, f"the trip has {len(ends)} End places"
    return str(ends[0])


# ---------------------------------------------------------------------------------- US-03: the loop trail
@given_step(parsers.re(r'track "(?P<track>[^"]+)" from "(?P<file_name>[^"]+)" starts and ends at (?P<place>.+)'))
def given_loop_track_starts_and_ends_at(world: PlannerWorld, track: str, file_name: str, place: str) -> None:
    assert TRACK_FILE_OF[track] == file_name, f"{track!r} comes from {TRACK_FILE_OF[track]}, not {file_name}"
    ensure_project(world, FIRST_TRIP)
    ensure_item(world, track)
    assert_track_from_to(world, track, place, place)
    # Not in the Gherkin: Calculate needs a Start and an End, so the trip is the feature's round trip from home.
    ensure_item(world, HOME)
    set_anchors(world, HOME, HOME)
    require_success(world, "set home as Start and End")


@then(parsers.re(r'"(?P<track>[^"]+)" is driven in its stored point order'))
def then_is_driven_in_stored_point_order(world: PlannerWorld, track: str) -> None:
    assert_first_plan_was_added(world)
    assert stop_named(world, track)["type"] == "track", f"{track!r} is not driven as a track"
    export_the_plan(world)  # the plan's file is where Marco sees every point in order
    driven = gpx_tracks(exported_file(world)).get(track)
    recorded = gpx_tracks(trail_file_bytes(TRACK_FILE_OF[track]))[track]
    assert driven, f"the plan's file holds no track {track!r}"
    assert driven == recorded, f"{track!r} is not driven in its recorded order ({len(driven)} points)"
    assert driven != list(reversed(recorded)), "the loop's recorded order must differ from its reverse"


# --------------------------------------------------------------------------- US-03: the guard (waiver W1)
@given_step(
    parsers.re(r'the optimizer proposes an order that drives "(?P<track>[^"]+)" from (?P<entry>.+) to (?P<exit>.+)')
)
def given_optimizer_proposes_reversed_order(world: PlannerWorld, track: str, entry: str, exit: str) -> None:
    solver = RuleBreakingTourSolver()
    world.tour_solver = solver
    prepare_day_trip(world)
    assert_track_from_to(world, track, exit, entry)  # the proposal drives it the other way round
    calculate_a_plan(world)  # the previous successful plan, worked out by the real optimizer
    world.scratch["previous_success"] = world.scratch["plan_run_id"]
    solver.drive_reversed(item_id_of(world, track))


@then("the plan is not shown and the plan run is marked Failed")
def then_plan_not_shown_and_run_failed(world: PlannerWorld) -> None:
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((2, "failed"))})
    detail = plan_run_detail(world, 2)
    assert detail["status"] == "failed" and detail["stops"] == [], f"plan run #2 shows a plan: {detail}"
    world.scratch["failed_run"] = detail


@then(parsers.re(r'its consideration report keeps the reason "(?P<reason>[^"]+)"'))
def then_report_keeps_reason(world: PlannerWorld, reason: str) -> None:
    detail = world.scratch["failed_run"]
    report = detail.get("report") or {}
    shown = report.get("reason") if isinstance(report, dict) else None
    assert shown is not None and reason in str(shown), (
        f"the report of plan run #2 does not keep the reason {reason!r}: report {report!r}, "
        f"failure_reason {detail.get('failure_reason')!r} (D206: the stored code is mapped to product words)"
    )


@then("the previous successful plan stays the latest successful run")
def then_previous_success_stays_latest(world: PlannerWorld) -> None:
    ready = [run for run in runs_by_number(world).values() if run["status"] == "ready"]
    latest = max(ready, key=lambda run: run["number"])
    assert str(latest["id"]) == world.scratch["previous_success"], f"the latest successful run is #{latest['number']}"


# ------------------------------------------------------------------------------ @property (layer 1-2, D192)
@given_step(
    parsers.re(
        r"(?P<count>\d+) randomly generated projects with (?P<low>\d+) to (?P<high>\d+) included items"
        r"(?P<anchors>, each with a round trip or a one-way Start and End)?"
    ),
    converters={"count": int, "low": int, "high": int},
)
def given_randomly_generated_projects(world: PlannerWorld, count: int, low: int, high: int) -> None:
    # Hypothesis profile ci (1,000 or more examples) runs the Gherkin's count; dev (100) and mutation (50) fewer (D192)
    profile_examples = settings.default.max_examples
    world.scratch["cases"] = count if profile_examples >= 1_000 else min(count, profile_examples)
    world.scratch["projects"] = generated_projects(low, high)  # every project has a round trip or one-way anchors


@when("a plan is generated for each")
def when_a_plan_is_generated_for_each(world: PlannerWorld) -> None:
    world.scratch["plan"] = plan_from_scratch(PROPERTY_BUDGET, cache={})
    world.scratch["seed"] = random.getrandbits(64)


@when("each is planned twice with the default search budget and without reusing earlier plans")
def when_each_is_planned_twice(world: PlannerWorld) -> None:
    def plan_twice(project: GeneratedProject) -> tuple[GeneratedPlan, GeneratedPlan]:
        return tuple(InMemoryComposition(project, DEFAULT_SEARCH_BUDGET).calculate() for _ in range(2))  # type: ignore[return-value]

    world.scratch["plan_twice"] = plan_twice
    world.scratch["seed"] = random.getrandbits(64)


def for_every_project(
    world: PlannerWorld, check: Callable[[GeneratedProject], None], *pinned: GeneratedProject
) -> None:
    """Run `check` over the generated projects of the Given, the pinned readable cases first."""

    def body(project: GeneratedProject) -> None:
        check(project)

    run = given(project=world.scratch["projects"])(body)
    for case in pinned:
        run = example(project=case)(run)
    run = settings(max_examples=world.scratch["cases"], deadline=None, suppress_health_check=HEALTH_CHECKS)(run)
    seed(world.scratch["seed"])(run)()


def _plan(world: PlannerWorld, project: GeneratedProject) -> GeneratedPlan:
    plan: Callable[[GeneratedProject], GeneratedPlan] = world.scratch["plan"]
    return plan(project)


@then("every track in every plan is driven from its stored entry to its stored exit")
def then_every_track_driven_entry_to_exit(world: PlannerWorld) -> None:
    def check(project: GeneratedProject) -> None:
        plan = _plan(world, project)
        guard_finds_nothing(plan)
        by_id = {item.id: item for item in project.snapshot.items}
        for stop in plan.stops:
            track = by_id[stop.item_id]
            if isinstance(track, TrackItem):
                points = project.stored_points(track)
                assert (stop.entry, stop.exit) == (points[0].coordinate, points[-1].coordinate), (
                    f"{track.id} is driven {stop.entry} -> {stop.exit}, stored {points[0]} -> {points[-1]}"
                )

    for_every_project(world, check, assietta_reversing_would_be_shorter(), day_trip_with_a_loop())


@then("every included track appears exactly once with all its stored points from entry to exit")
def then_every_included_track_once_in_full(world: PlannerWorld) -> None:
    def check(project: GeneratedProject) -> None:
        plan = _plan(world, project)
        guard_finds_nothing(plan)
        for track in project.tracks_to_drive():
            driven = [stop for stop in plan.stops if stop.item_id == track.id]
            assert len(driven) == 1, f"{track.id} is driven {len(driven)} times"
            stored = project.evidence()[track.id]
            assert (driven[0].point_count, driven[0].canonical_sha256) == (stored.point_count, stored.sha256), (
                f"{track.id} is not driven with all its {stored.point_count} stored points"
            )
            assert (driven[0].entry, driven[0].exit) == (stored.first, stored.last), f"{track.id} is cut short"
        excluded = {item.id for item in project.snapshot.items if not item.included}
        assert not excluded & {stop.item_id for stop in plan.stops}, "an Excluded item is driven"

    for_every_project(world, check, day_trip_with_a_loop(), assietta_reversing_would_be_shorter())


US_04_SEEDS = (  # US-04 S1's readable seeds: (items, seed, Start, End)
    (5, 11, HOME, HOME),
    (23, 42, HOME, AOSTA),
    (60, 7, "Cuneo", BRIANCON),
)


@then("the first stop of every plan is its Start")
def then_first_stop_is_start(world: PlannerWorld) -> None:
    def check(project: GeneratedProject) -> None:
        first = _plan(world, project).stops[0]
        assert first.item_id == project.snapshot.start_item_id, f"the trip starts at {first.item_id}"
        assert first.leg_km is None, "the trip's first stop has a road leg into it"

    for_every_project(world, check, *(seeded_project(*case) for case in US_04_SEEDS))


@then("the last stop of every plan is its End")
def then_last_stop_is_end(world: PlannerWorld) -> None:
    def check(project: GeneratedProject) -> None:
        last = _plan(world, project).stops[-1]
        assert last.item_id == project.snapshot.end_item_id, f"the trip ends at {last.item_id}"

    for_every_project(world, check, *(seeded_project(*case) for case in US_04_SEEDS))


@then("both plans of every project have the same order, legs and totals")
def then_both_plans_are_the_same(world: PlannerWorld) -> None:
    plan_twice: Callable[[GeneratedProject], tuple[GeneratedPlan, GeneratedPlan]] = world.scratch["plan_twice"]

    def check(project: GeneratedProject) -> None:
        first, second = plan_twice(project)
        assert [s.item_id for s in first.stops] == [s.item_id for s in second.stops], "the order differs"
        assert [s.leg_km for s in first.stops] == [s.leg_km for s in second.stops], "the legs differ"
        totals = [getattr(plan.detail, "totals", None) for plan in (first, second)]
        assert totals[0] is not None, "the plan run has no totals"
        assert totals[0] == totals[1], f"the totals differ: {totals}"

    for_every_project(world, check, day_trip_with_a_loop())


# ------------------------------------------------------------------------------- US-04: anchors and refusals
@given_step(parsers.re(r'project "(?P<project>[^"]+)" has no (?P<anchor>Start|End)'))
def given_project_has_no_anchor(world: PlannerWorld, project: str, anchor: str) -> None:
    """The trip had both anchors; Marco then removed the place that was the missing one (US-04 S4's action)."""
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} is set up here"
    prepare_day_trip(world)
    ensure_item(world, AOSTA)
    start, end = (AOSTA, HOME) if anchor == "Start" else (HOME, AOSTA)
    set_anchors(world, start, end)
    require_success(world, f"set {start!r} as Start and {end!r} as End")
    remove_item(world, AOSTA)
    require_success(world, f"remove {AOSTA!r}")


@given_step(parsers.re(r'project "(?P<project>[^"]+)" contains track "(?P<track>[^"]+)" and POI "(?P<poi>[^"]+)"'))
def given_project_contains_track_and_poi(world: PlannerWorld, project: str, track: str, poi: str) -> None:
    ensure_project(world, project)
    ensure_item(world, track)
    ensure_item(world, poi)


@when("Marco opens the Start choices")
def when_marco_opens_the_start_choices(world: PlannerWorld) -> None:
    assert world.project_id is not None, "no project is open"
    answer = world.marco().items_of_type(world.project_id, "poi")
    assert answer.status_code == 200, f"the Start choices did not open: {answer.status_code} {answer.text[:300]}"
    world.scratch["start_choices"] = [item["name"] for item in answer.json()]


@then(parsers.re(r'"(?P<name>(?!Re-optimise )[^"]+)" is offered'))  # Re-optimise: performance_steps (slice 03)
def then_is_offered(world: PlannerWorld, name: str) -> None:
    assert name in world.scratch["start_choices"], f"the Start choices are {world.scratch['start_choices']}"


@then(parsers.re(r'"(?P<name>[^"]+)" is not offered'))
def then_is_not_offered(world: PlannerWorld, name: str) -> None:
    assert name not in world.scratch["start_choices"], f"the Start choices are {world.scratch['start_choices']}"


@when(parsers.re(r'Marco tries to set "(?P<name>[^"]+)" as Start'))
def when_marco_tries_to_set_as_start(world: PlannerWorld, name: str) -> None:
    assert world.project_id is not None, "no project is open"
    ends = [item["id"] for item in world.items() if item.get("anchor") in ("end", "start_end")]
    world.before = world.catalog_view()
    world.note(world.marco().set_anchors(world.project_id, item_id_of(world, name), ends[0] if ends else None))
    world.after = world.catalog_view()


@then("the Start and End are unchanged")
def then_start_and_end_unchanged(world: PlannerWorld) -> None:
    assert_state_delta(world.before, world.after, CATALOG_UNIVERSE, {})


@when(parsers.re(r'Marco confirms the removal of "(?P<name>[^"]+)" from the project'))
def when_marco_confirms_the_removal(world: PlannerWorld, name: str) -> None:
    remove_item(world, name)
    world.scratch["removed"] = name


@then("the project has no Start and no End")
def then_project_has_no_start_and_no_end(world: PlannerWorld) -> None:
    require_success(world, f"remove {world.scratch['removed']!r}")
    removed = world.scratch["removed"]
    assert_state_delta(
        world.before,
        world.after,
        PLANNING_UNIVERSE,
        {"project.items": lambda old, new: new == tuple(row for row in old if row[1] != removed)},
    )
    anchored = [row for row in world.after["project.items"] if row[3] is not None]
    assert anchored == [], f"items still anchored: {anchored}"


@then("the plan is marked Stale")
def then_the_plan_is_marked_stale(world: PlannerWorld) -> None:
    """The run the Given computed before the removal (D217); its number is not asserted (branch fixture)."""
    computed = world.scratch.get("plan_run_id")
    assert computed is not None, "no plan run was computed before the removal"
    run = next((run for run in runs_by_number(world).values() if str(run["id"]) == computed), None)
    assert run is not None, f"the plan run computed before the removal is gone: {computed}"
    assert run.get("stale") is True, f"the plan computed before the removal is not marked Stale: {run}"


@then(parsers.re(r'Calculate is refused with "(?P<message>[^"]+)"'))
def then_calculate_is_refused_with(world: PlannerWorld, message: str) -> None:
    press_calculate(world)
    answer = world.response
    assert answer is not None and answer.status_code == 422, f"Calculate was not refused: {answer and answer.text}"
    assert answer.json() == {"code": "missing_anchor", "message": message}, answer.text
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {})


@given_step(
    parsers.re(
        r'project "(?P<project>[^"]+)" has Start "(?P<start>[^"]+)" and End "(?P<end>[^"]+)" and nothing else Included'
    )
)
def given_project_with_start_and_end_only(world: PlannerWorld, project: str, start: str, end: str) -> None:
    ensure_project(world, project)
    ensure_item(world, start)
    ensure_item(world, end)
    set_anchors(world, start, end)
    require_success(world, f"set {start!r} as Start and {end!r} as End")
    included = sorted(item["name"] for item in world.items() if item["included"])
    assert included == sorted({start, end}), f"Included: {included}"


@then(parsers.re(r'the itinerary is "(?P<first>[^"]+)" then "(?P<second>[^"]+)" with one road leg'))
def then_the_itinerary_is_with_one_road_leg(world: PlannerWorld, first: str, second: str) -> None:
    assert_first_plan_was_added(world)
    itinerary = stops(world)
    assert [stop["name"] for stop in itinerary] == [first, second], f"the itinerary is {itinerary}"
    assert itinerary[0]["leg_km"] is None, f"{first} has a road leg into it"
    assert_km(itinerary[1]["leg_km"], expected_road_km(world, first, second), f"the leg into {second}")


@then("the totals show that road leg and no off-road driving")
def then_totals_show_that_leg_and_no_offroad(world: PlannerWorld) -> None:
    detail = plan_run_detail(world, max(runs_by_number(world)))
    totals = totals_of(detail)
    leg = detail["stops"][1]
    assert_km(totals["road_km"], leg["leg_km"], "road")
    assert (totals["offroad_km"], totals["offroad_s"]) == (0, 0), f"off-road driving in the totals: {totals}"
    assert totals["road_s"] > 0, f"the road leg takes no time: {totals}"
    assert (totals["total_km"], totals["total_s"]) == (totals["road_km"], totals["road_s"]), f"totals: {totals}"


# ------------------------------------------------------------------------- US-05: the same plan every time
@given_step(parsers.re(r'plan run #1 of "(?P<project>[^"]+)" has been computed'))
def given_plan_run_1_has_been_computed(world: PlannerWorld, project: str) -> None:
    assert project == DOLOMITI, f"only {DOLOMITI!r} is set up here"
    ensure_project(world, project)
    for name in ("Cortina d'Ampezzo", "Lago di Braies", *DOLOMITI_PLACES):
        ensure_item(world, name)
    set_anchors(world, "Cortina d'Ampezzo", "Lago di Braies")
    require_success(world, "set Cortina as Start and Lago di Braies as End")
    calculate_a_plan(world)


@given_step("plan run #2 was recalculated without any change")
def given_plan_run_2_recalculated(world: PlannerWorld) -> None:
    calculate_a_plan(world)


@given_step("the planner was then restarted")
def given_the_planner_was_restarted(world: PlannerWorld) -> None:
    assert world.planner is not None, "the planner is not running"
    world.planner.restart()


@when("Marco recalculates without changing anything")
def when_marco_recalculates_without_changes(world: PlannerWorld) -> None:
    calculate_a_plan(world)


@then(parsers.re(r'plan runs #2 and #3 of "(?P<project>[^"]+)" have the same order, legs and totals as plan run #1'))
def then_runs_2_and_3_same_as_1(world: PlannerWorld, project: str) -> None:
    assert world.project_name == project
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((3, "ready"))})
    runs = [plan_run_detail(world, number) for number in (1, 2, 3)]

    def shape(detail: dict[str, Any]) -> tuple[Any, ...]:
        return (
            [stop["name"] for stop in detail["stops"]],
            [stop["leg_km"] for stop in detail["stops"]],
            totals_of(detail),
        )

    first = shape(runs[0])
    for number, detail in ((2, runs[1]), (3, runs[2])):
        assert shape(detail) == first, f"plan run #{number} differs from #1: {shape(detail)} != {first}"


# ------------------------------------------------------------------------------------ US-05: honest totals
@given_step(
    parsers.re(rf"plan run #4 has road legs totalling (?P<km>[\d.]+) km and (?P<time>{DURATION}) \(scripted road map\)")
)
def given_plan_run_4_with_road_legs_totalling(world: PlannerWorld, km: str, time: str) -> None:
    compute_plan_run_4(world)  # the scripted road map's trip legs total these (fixtures/road-maps/plan-run-4.yaml)


@given_step(
    parsers.re(
        r'it includes tracks "(?P<a>[^"]+)" (?P<akm>[\d.]+) km, "(?P<b>[^"]+)" (?P<bkm>[\d.]+) km '
        r'and "(?P<c>[^"]+)" (?P<ckm>[\d.]+) km'
    ),
    converters={"akm": float, "bkm": float, "ckm": float},
)
def given_it_includes_tracks(world: PlannerWorld, a: str, akm: float, b: str, bkm: float, c: str, ckm: float) -> None:
    tracks = {item["name"]: item for item in world.items() if item["type"] == "track" and item["included"]}
    assert sorted(tracks) == sorted((a, b, c)), f"the Included tracks are {sorted(tracks)}"
    for name, km in ((a, akm), (b, bkm), (c, ckm)):
        assert round(float(tracks[name]["length_m"]) / 1000.0, 1) == km, f"{name} is {tracks[name]['length_m']} m"


@given_step(
    parsers.re(
        r'in plan run #4 the leg from "(?P<origin>[^"]+)" to the entry of "(?P<track>[^"]+)" is (?P<km>[\d.]+) km '
        r"\(scripted road map\)"
    )
)
def given_in_plan_run_4_the_leg_is(world: PlannerWorld, origin: str, track: str, km: str) -> None:
    compute_plan_run_4(world)  # Casa Marco -> Pian dell'Alpe is 86.1 km on that road map


@when(parsers.re(r"Marco opens the (?:results|itinerary) of plan run #(?P<number>\d+)"), converters={"number": int})
def when_marco_opens_plan_run(world: PlannerWorld, number: int) -> None:
    world.scratch["opened_run"] = plan_run_detail(world, number)


@then(
    parsers.re(r"the totals show road (?P<road>[\d.]+) km, off-road (?P<off>[\d.]+) km and total (?P<total>[\d.]+) km"),
    converters={"road": float, "off": float, "total": float},
)
def then_the_totals_show_km(world: PlannerWorld, road: float, off: float, total: float) -> None:
    totals = totals_of(opened(world))
    for key, km in (("road_km", road), ("offroad_km", off), ("total_km", total)):
        assert_km(totals.get(key), km, key)


@then(parsers.re(rf"road (?P<road>{DURATION}), off-road (?P<off>{DURATION}) and total (?P<total>{DURATION})"))
def then_the_totals_show_time(world: PlannerWorld, road: str, off: str, total: str) -> None:
    totals = totals_of(opened(world))
    shown = tuple(hours_minutes(totals[key]) for key in ("road_s", "offroad_s", "total_s"))
    assert shown == (road, off, total), f"the totals show {shown}"


@then(
    parsers.re(
        rf'row (?P<row>\d+) shows "(?P<name>[^"]+)", type (?P<kind>Track|POI), leg (?P<leg>[\d.]+) km, '
        rf"cumulative (?P<cumulative>[\d.]+) km, track (?P<track>[\d.]+) km and (?P<time>{DURATION})"
    ),
    converters={"row": int, "leg": float, "cumulative": float, "track": float},
)
def then_row_shows(
    world: PlannerWorld, row: int, name: str, kind: str, leg: float, cumulative: float, track: float, time: str
) -> None:
    stop = itinerary_rows(opened(world))[row - 1]
    assert (stop["name"], stop["type"]) == (name, kind.lower()), f"row {row} is {stop['name']} ({stop['type']})"
    assert_km(stop["leg_km"], leg, f"row {row} leg")
    assert_km(stop.get("cumulative_km"), cumulative, f"row {row} cumulative")
    assert_km(stop.get("track_km"), track, f"row {row} track")
    assert stop.get("offroad_s") is not None, f"row {row} shows no off-road duration: {stop}"
    assert hours_minutes(stop["offroad_s"]) == time, f"row {row} shows {hours_minutes(stop['offroad_s'])}"


@then("cumulative distance is road plus off-road km driven up to the end of that stop")
def then_cumulative_is_road_plus_offroad(world: PlannerWorld) -> None:
    driven = 0.0
    for number, stop in enumerate(itinerary_rows(opened(world)), start=1):
        driven += (stop["leg_km"] or 0.0) + (stop.get("track_km") or 0.0)
        assert_km(stop.get("cumulative_km"), round(driven, 1), f"row {number} cumulative")


@given_step(
    parsers.re(r'project "(?P<project>[^"]+)" has off-road speed (?P<speed>-?\d+) km/h'), converters={"speed": int}
)
def given_project_has_offroad_speed(world: PlannerWorld, project: str, speed: int) -> None:
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} is set up here"
    prepare_day_trip(world)
    set_offroad_speed(world, speed)
    require_success(world, f"set the off-road speed to {speed} km/h")


@when("Marco recalculates")
def when_marco_recalculates(world: PlannerWorld) -> None:
    press_calculate(world)
    if world.response is not None and world.response.status_code == 202:
        wait_for_plan(world)


@then(parsers.re(rf'"(?P<track>[^"]+)" shows an off-road duration of (?P<time>{DURATION})'))
def then_track_shows_offroad_duration(world: PlannerWorld, track: str, time: str) -> None:
    assert_first_plan_was_added(world)
    shown = stop_named(world, track).get("offroad_s")
    assert shown is not None, f"{track!r} shows no off-road duration: {stop_named(world, track)}"
    assert hours_minutes(shown) == time, f"{track!r} shows {hours_minutes(shown)}"


@when(parsers.re(r"Marco sets the off-road speed to (?P<speed>-?\d+) km/h"), converters={"speed": int})
def when_marco_sets_the_offroad_speed(world: PlannerWorld, speed: int) -> None:
    set_offroad_speed(world, speed)


@then(parsers.re(r"the off-road speed is still (?P<speed>\d+) km/h"), converters={"speed": int})
def then_the_offroad_speed_is_still(world: PlannerWorld, speed: int) -> None:
    assert_state_delta(world.before, world.after, CATALOG_UNIVERSE | {"project.offroad_speed_kmh"}, {})
    assert world.after["project.offroad_speed_kmh"] == speed, f"the off-road speed is {world.after}"


# -------------------------------------------------------------------------------- US-05: Giulia's phone
@given_step(parsers.re(r'plan run #4 of "(?P<project>[^"]+)"'))
def given_plan_run_4_of(world: PlannerWorld, project: str) -> None:
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} has a plan run #4 here"
    world.environ["MOCK_PLAN"] = str(PLAN_RUN_4_ROAD_MAP)
    server = ServerPlanner(world.environ, REPO_ROOT)  # policy: the browser needs a real server (Driving, Browser UI)
    world.planner = server
    server.start()
    compute_plan_run_4(world)


@when(parsers.re(r"Giulia opens the results on a (?P<width>\d+) px wide phone screen"), converters={"width": int})
def when_giulia_opens_the_results_on_her_phone(world: PlannerWorld, width: int) -> None:
    assert width == PhoneItineraryJourney.SCREEN_WIDTH, (
        f"the phone journey runs at {PhoneItineraryJourney.SCREEN_WIDTH} px"
    )
    assert isinstance(world.planner, ServerPlanner) and world.project_id is not None
    journey = PhoneItineraryJourney(world.project_id, world.data_dir.parent / "phone")
    world.scratch["phone_view"] = journey.run(world.planner.base_url)


@then("she can read every stop and the totals without horizontal scrolling")
def then_she_reads_every_stop_and_the_totals(world: PlannerWorld) -> None:
    view: PhoneView = world.scratch["phone_view"]
    assert view.page_width <= view.screen_width, (
        f"the page is {view.page_width} px wide on a {view.screen_width} px screen"
    )
    itinerary = itinerary_rows(plan_run_detail(world, 4))
    assert len(view.rows) == len(itinerary), f"the phone shows {len(view.rows)} rows for {len(itinerary)} stops"
    for number, (row, stop) in enumerate(zip(view.rows, itinerary, strict=True), start=1):
        assert row["visible"] and stop["name"] in row["text"], f"row {number} should show {stop['name']!r}: {row}"
        assert row["left"] >= 0 and row["right"] <= view.screen_width, f"row {number} runs off the screen: {row}"
    totals = totals_of(plan_run_detail(world, 4))
    assert view.totals_text is not None, "the phone shows no totals"
    for key in ("road_km", "offroad_km", "total_km"):
        assert f"{totals[key]:.1f} km" in view.totals_text, (
            f"the totals do not show {totals[key]:.1f} km: {view.totals_text!r}"
        )
    for key in ("road_s", "offroad_s", "total_s"):
        assert hours_minutes(totals[key]) in view.totals_text, f"the totals do not show {hours_minutes(totals[key])}"

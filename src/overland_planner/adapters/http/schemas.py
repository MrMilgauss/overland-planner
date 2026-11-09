"""HTTP request/response bodies (brief §5, D130): snake_case fields, ids as strings."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from overland_planner.application.planning.facade import PlanJobState, PlanJobView
from overland_planner.application.platform.facade import DiagnosticsReport
from overland_planner.application.ports.plan_run_repository import PlanRunDetail
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, ItemType, TrackItem
from overland_planner.domain.catalog.poi import AnchorRole
from overland_planner.domain.catalog.project import Project
from overland_planner.domain.planning.plan_run import PlanReport, PlanRun, PlanRunStatus, PlanStop, StopKind, Totals
from overland_planner.domain.planning.run_messages import NotFullyOptimised


class ErrorEnvelope(BaseModel):
    """Every non-2xx answer under /api (D183)."""

    code: str
    message: str


class ProjectCreate(BaseModel):
    name: str


class ProjectUpdate(BaseModel):
    """The project's settings. The speed rule (above 0, finite) is the domain's, so it is not checked here."""

    offroad_speed_kmh: float


class PoiCreate(BaseModel):
    """A place by decimal degrees. The ranges are the domain's rule (D151 reasons), so they are not checked here."""

    name: str
    lat: float
    lon: float


class AnchorsChoice(BaseModel):
    """The Start and End item ids (HC-2): POIs of the project, one POI for both on a round trip; `null` unsets one."""

    start_item_id: str | None
    end_item_id: str | None


class ProjectResource(BaseModel):
    id: str
    name: str
    revision: int
    offroad_speed_kmh: float

    @classmethod
    def of(cls, project: Project) -> ProjectResource:
        return cls(
            id=project.id,
            name=project.name.value,
            revision=project.revision,
            offroad_speed_kmh=project.offroad_speed.kmh,
        )


class PointResource(BaseModel):
    lat: float
    lon: float

    @classmethod
    def of(cls, coordinate: Coordinate) -> PointResource:
        return cls(lat=coordinate.latitude, lon=coordinate.longitude)


class ItemResource(BaseModel):
    """A catalog item (D107): `location` for a POI; `entry`, `exit` and `length_m` for a track; others null."""

    id: str
    type: ItemType
    name: str
    included: bool
    anchor: AnchorRole | None
    location: PointResource | None
    entry: PointResource | None
    exit: PointResource | None
    length_m: float | None

    @classmethod
    def of(cls, item: CatalogItem) -> ItemResource:
        if isinstance(item, TrackItem):
            entry, exit_ = PointResource.of(item.entry), PointResource.of(item.exit)
            return cls._with(item, entry=entry, exit=exit_, length_m=item.length_m)
        return cls._with(item, location=PointResource.of(item.location))

    @classmethod
    def _with(
        cls,
        item: CatalogItem,
        *,
        location: PointResource | None = None,
        entry: PointResource | None = None,
        exit: PointResource | None = None,
        length_m: float | None = None,
    ) -> ItemResource:
        """The fields every item has, plus the type-specific ones (null when the type has none)."""
        return cls(
            id=item.id,
            type=item.type,
            name=item.name,
            included=item.included,
            anchor=item.anchor,
            location=location,
            entry=entry,
            exit=exit,
            length_m=length_m,
        )


class PlanRunResource(BaseModel):
    """A numbered plan run; a job still running has none. `stale`: the project changed since it was computed.
    `reproducible` is false when its search did not end on its budget; `not_fully_optimised` names why a ready run is
    not (brief section 8 run flags), null otherwise."""

    id: str
    number: int
    status: PlanRunStatus
    stale: bool
    reproducible: bool
    not_fully_optimised: NotFullyOptimised | None

    @classmethod
    def of(cls, run: PlanRun) -> PlanRunResource:
        return cls(
            id=run.id,
            number=run.number,
            status=run.status,
            stale=run.stale,
            reproducible=run.reproducible,
            not_fully_optimised=run.not_fully_optimised,
        )


class PlanJobAccepted(BaseModel):
    job_id: str


class IncumbentResource(BaseModel):
    """The last valid route found while optimising: its legs not yet confirmed, its retraces, the optimizer's cost of
    it and when it was found, in seconds from the job's start."""

    unconfirmed_legs: int
    retraces: int
    objective: float
    found_at_s: float


class PlanJobResource(BaseModel):
    """The poll payload (brief §5): the subset filled so far; later fields are additive. `memo_hit` is true when the
    order came from the fingerprint memo (05-10) instead of a solve. `stage_ms` holds the whole milliseconds of each
    stage finished so far (`snapshot`, `matrix`, `reach_model`, `solve`, `guard_persist`; no `solve` on a memo hit);
    `legs_total` and `items_included` are null until known; `incumbent` is null until the first valid route. An ended
    job's `message` names its Failed run in words when the run has them (D151)."""

    state: PlanJobState
    reason: str | None
    message: str | None
    plan_run_id: str | None
    elapsed_s: float
    memo_hit: bool
    ignore_memo: bool
    stage_ms: dict[str, int] | None
    legs_total: int | None
    items_included: int | None
    incumbent: IncumbentResource | None

    @classmethod
    def of(cls, job: PlanJobView) -> PlanJobResource:
        return cls.model_validate(job, from_attributes=True)


class PlanStopResource(BaseModel):
    """One stop of the itinerary (FR-6.1): the first has no road leg; a track shows its entry and exit (HC-1), its
    length and off-road time, a POI none. Km and seconds are unrounded; a run stored before them shows them null."""

    name: str
    type: StopKind
    leg_km: float | None
    entry: PointResource | None
    exit: PointResource | None
    leg_s: int | None
    track_km: float | None
    offroad_s: float | None
    cumulative_km: float | None
    cumulative_s: float | None

    @classmethod
    def of(cls, stop: PlanStop) -> PlanStopResource:
        entry = None if stop.entry is None else PointResource.of(stop.entry)
        exit_ = None if stop.exit is None else PointResource.of(stop.exit)
        return cls(
            name=stop.name,
            type=stop.kind,
            leg_km=stop.leg_km,
            entry=entry,
            exit=exit_,
            leg_s=stop.leg_s,
            track_km=stop.track_km,
            offroad_s=stop.offroad_s,
            cumulative_km=stop.cumulative_km,
            cumulative_s=stop.cumulative_s,
        )


class TotalsResource(BaseModel):
    """The plan's road, off-road and total driving (FR-6.2), in km and seconds, unrounded: rounding is the web's."""

    road_km: float
    road_s: int
    offroad_km: float
    offroad_s: float
    total_km: float
    total_s: float

    @classmethod
    def of(cls, totals: Totals) -> TotalsResource:
        return cls.model_validate(totals, from_attributes=True)


class PlanReportResource(BaseModel):
    """Why a Failed run has no plan, in product words (D206); the code stays in `failure_reason`."""

    reason: str

    @classmethod
    def of(cls, report: PlanReport) -> PlanReportResource:
        return cls.model_validate(report, from_attributes=True)


class PlanRunDetailResource(BaseModel):
    """A plan run with its ordered stops and totals; a Failed run has neither, names its `failure_reason` and keeps the
    reason in product words in `report`. A ready run shows `report` null, as does any run stored before 05-08; a run
    stored before the totals were (0006) shows `totals` null. `reproducible` and `not_fully_optimised` are the run
    flags (`not_fully_optimised`: `optimizer_failed` or `time_limit`); `messages` the lines the results show in words,
    such as "not fully optimised (time limit)" or, for a run failed on the feasibility limit, "No valid route found
    within the time limit - plan run #N failed" (D151)."""

    id: str
    project_id: str
    number: int
    status: PlanRunStatus
    failure_reason: str | None
    stops: list[PlanStopResource]
    totals: TotalsResource | None
    report: PlanReportResource | None
    reproducible: bool
    not_fully_optimised: NotFullyOptimised | None
    messages: list[str]

    @classmethod
    def of(cls, run: PlanRunDetail) -> PlanRunDetailResource:
        return cls(
            id=run.id,
            project_id=run.project_id,
            number=run.number,
            status=run.status,
            failure_reason=run.failure_reason,
            stops=[PlanStopResource.of(stop) for stop in run.stops],
            totals=None if run.totals is None else TotalsResource.of(run.totals),
            report=None if run.report is None else PlanReportResource.of(run.report),
            reproducible=run.reproducible,
            not_fully_optimised=run.not_fully_optimised,
            messages=list(run.messages),
        )


class K2Resource(BaseModel):
    """Plan runs that broke a hard rule (Failed with `internal_invariant_violation`): `all_time` and `window`."""

    invariant_violations: dict[str, int]


class K3Resource(BaseModel):
    """Plan runs whose stops left out an item they were asked to visit: `all_time` and `window`."""

    report_omissions: dict[str, int]


class K5Resource(BaseModel):
    """Planning time, a server-side proxy (D177): nearest-rank p95 in seconds (the max below 20 jobs) over the cold
    jobs of the window, done, failed and cancelled alike; per-band fields are keyed le_30, 31_59, 60, 61_70 and a band
    without a job shows null. `e2e_source` names what e2e measures (`elapsed_ms` until slice 06a). The counts are
    shown apart and stay in every p95, except memo hits, which are not cold plans."""

    stage_p95_s: dict[str, float | None]
    solve_p95_s: dict[str, float | None]
    e2e_p95_s: float | None
    e2e_p95_by_band_s: dict[str, float | None]
    e2e_source: str
    retried_jobs: dict[str, int]
    second_pass_gt_700_jobs: dict[str, int]
    failed_jobs: dict[str, int]
    cancelled_jobs: dict[str, int]
    memo_hit_jobs: dict[str, int]


class RunsPerProjectDayResource(BaseModel):
    median: float | None
    max: int | None


class K7Resource(BaseModel):
    """Done jobs per project and local day (Europe/Rome), projects named '__...' left out; null without a job."""

    runs_per_project_day: RunsPerProjectDayResource


class DiagnosticsResource(BaseModel):
    """`GET /api/diagnostics` (DV-3, kpi-contracts `diagnostics_endpoint`) over the last `days` days. `k1`, `k4`,
    `g1`, `g2`, `g4` and `cache_hit_rate_30d` stay null until the slices that own their sources."""

    version: str
    process_started_at: str
    days: int
    k1: None = None
    k2: K2Resource
    k3: K3Resource
    k4: None = None
    k5: K5Resource
    k7: K7Resource
    g1: None = None
    g2: None = None
    g4: None = None
    cache_hit_rate_30d: None = None
    jobs_by_terminal_state_30d: dict[str, int]
    retried_jobs_30d: int
    second_pass_jobs_30d: int

    @classmethod
    def of(cls, report: DiagnosticsReport) -> DiagnosticsResource:
        return cls(
            version=report.version,
            process_started_at=report.process_started_at.isoformat(),
            days=report.days,
            k2=K2Resource.model_validate(report.k2, from_attributes=True),
            k3=K3Resource.model_validate(report.k3, from_attributes=True),
            k5=K5Resource.model_validate(report.k5, from_attributes=True),
            k7=K7Resource.model_validate(report.k7, from_attributes=True),
            jobs_by_terminal_state_30d=dict(report.jobs_by_terminal_state),
            retried_jobs_30d=report.retried_jobs,
            second_pass_jobs_30d=report.second_pass_jobs,
        )


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "not_found"},
    422: {"model": ErrorEnvelope, "description": "validation_error"},
}
CALCULATE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    409: {"model": ErrorEnvelope, "description": "job_active"},
    422: {"model": ErrorEnvelope, "description": "missing_anchor, validation_error"},
    503: {"model": ErrorEnvelope, "description": "optimizer_unavailable"},
}

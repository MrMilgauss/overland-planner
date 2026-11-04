"""HTTP request/response bodies (brief §5, D130): snake_case fields, ids as strings."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from overland_planner.application.planning.facade import PlanJobState, PlanJobView
from overland_planner.application.ports.plan_run_repository import PlanRunDetail
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, ItemType, TrackItem
from overland_planner.domain.catalog.poi import AnchorRole
from overland_planner.domain.catalog.project import Project
from overland_planner.domain.planning.plan_run import PlanRun, PlanRunStatus, PlanStop, StopKind


class ErrorEnvelope(BaseModel):
    """Every non-2xx answer under /api (D183)."""

    code: str
    message: str


class ProjectCreate(BaseModel):
    name: str


class PoiCreate(BaseModel):
    """A place by decimal degrees. The ranges are the domain's rule (D151 reasons), so they are not checked here."""

    name: str
    lat: float
    lon: float


class AnchorsChoice(BaseModel):
    """The Start and End item ids (HC-2): POIs of the project, the same one for a round trip. Both required in 01a."""

    start_item_id: str
    end_item_id: str


class ProjectResource(BaseModel):
    id: str
    name: str
    revision: int

    @classmethod
    def of(cls, project: Project) -> ProjectResource:
        return cls(id=project.id, name=project.name.value, revision=project.revision)


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
    """A numbered plan run; a job still running has none."""

    id: str
    number: int
    status: PlanRunStatus

    @classmethod
    def of(cls, run: PlanRun) -> PlanRunResource:
        return cls(id=run.id, number=run.number, status=run.status)


class PlanJobAccepted(BaseModel):
    job_id: str


class PlanJobResource(BaseModel):
    """The poll payload (brief §5): the subset slice 01b fills; later fields are additive."""

    state: PlanJobState
    reason: str | None
    message: str | None
    plan_run_id: str | None
    elapsed_s: float

    @classmethod
    def of(cls, job: PlanJobView) -> PlanJobResource:
        return cls(
            state=job.state,
            reason=job.reason,
            message=job.message,
            plan_run_id=job.plan_run_id,
            elapsed_s=job.elapsed_s,
        )


class PlanStopResource(BaseModel):
    """One stop of the itinerary: the first has no road leg; a track shows its entry and exit (HC-1), a POI none."""

    name: str
    type: StopKind
    leg_km: float | None
    entry: PointResource | None
    exit: PointResource | None

    @classmethod
    def of(cls, stop: PlanStop) -> PlanStopResource:
        entry = None if stop.entry is None else PointResource.of(stop.entry)
        exit_ = None if stop.exit is None else PointResource.of(stop.exit)
        return cls(name=stop.name, type=stop.kind, leg_km=stop.leg_km, entry=entry, exit=exit_)


class PlanRunDetailResource(BaseModel):
    """A plan run with its ordered stops; a Failed run has none and names its `failure_reason`."""

    id: str
    project_id: str
    number: int
    status: PlanRunStatus
    failure_reason: str | None
    stops: list[PlanStopResource]

    @classmethod
    def of(cls, run: PlanRunDetail) -> PlanRunDetailResource:
        return cls(
            id=run.id,
            project_id=run.project_id,
            number=run.number,
            status=run.status,
            failure_reason=run.failure_reason,
            stops=[PlanStopResource.of(stop) for stop in run.stops],
        )


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "not_found"},
    422: {"model": ErrorEnvelope, "description": "validation_error"},
}
CALCULATE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    422: {"model": ErrorEnvelope, "description": "missing_anchor"},
    503: {"model": ErrorEnvelope, "description": "optimizer_unavailable"},
}

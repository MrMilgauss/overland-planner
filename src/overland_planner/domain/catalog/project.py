"""Trip project (brief §3), its name rule (D151) and off-road speed (FR-4.6). Pure domain: standard library only."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from overland_planner.domain.catalog.anchors import Anchors


class ProjectNameRequiredError(ValueError):
    """A project name is empty once its surrounding whitespace is trimmed."""

    def __init__(self) -> None:
        super().__init__("Give the project a name")


@dataclass(frozen=True)
class ProjectName:
    """A project name: surrounding whitespace trimmed, never empty."""

    value: str

    def __init__(self, raw: str) -> None:
        trimmed = raw.strip()
        if not trimmed:
            raise ProjectNameRequiredError()
        object.__setattr__(self, "value", trimmed)


class OffroadSpeedNotDrivableError(ValueError):
    """An off-road speed of 0 or less, or not a finite number."""

    def __init__(self) -> None:
        super().__init__("Off-road speed must be more than 0 km/h")


@dataclass(frozen=True)
class OffroadSpeed:
    """The speed a track is driven at, in km/h: finite and above 0. 15 km/h unless the project sets another (FR-4.6)."""

    kmh: float

    def __init__(self, kmh: float) -> None:
        if not (math.isfinite(kmh) and kmh > 0):
            raise OffroadSpeedNotDrivableError()
        object.__setattr__(self, "kmh", kmh)


DEFAULT_OFFROAD_SPEED = OffroadSpeed(15)


class ObjectiveUnknownError(ValueError):
    """An objective that is neither `distance` nor `time`."""

    def __init__(self) -> None:
        super().__init__("The objective is `distance` or `time`")


class NothingToChangeError(ValueError):
    """A settings change that names no setting."""

    def __init__(self) -> None:
        super().__init__("Give the objective or the off-road speed to change")


class Objective(StrEnum):
    """What a plan minimises: the road metres (the default) or the road seconds of the same legs (D249)."""

    DISTANCE = "distance"
    TIME = "time"

    @classmethod
    def parse(cls, raw: str) -> Objective:
        try:
            return cls(raw)
        except ValueError:
            raise ObjectiveUnknownError() from None

    @property
    def label(self) -> str:
        return f"minimise road {self.value}"


@dataclass(frozen=True)
class Project:
    """A trip project. `revision` counts its changes (brief §3, stale detection); creation is change 1."""

    id: str
    name: ProjectName
    revision: int
    created_at: datetime
    anchors: Anchors = field(default_factory=Anchors)
    offroad_speed: OffroadSpeed = DEFAULT_OFFROAD_SPEED
    objective: Objective = Objective.DISTANCE

    @classmethod
    def create(cls, project_id: str, name: ProjectName, created_at: datetime) -> Project:
        return cls(id=project_id, name=name, revision=1, created_at=created_at)

    def revised(self) -> Project:
        """The project after one more catalog change (brief §3: each change increments the revision)."""
        return replace(self, revision=self.revision + 1)

    def anchored(self, anchors: Anchors) -> Project:
        """The project with new Start and End, replacing the previous ones: one more catalog change."""
        return replace(self, anchors=anchors).revised()

    def item_removed(self, item_id: str) -> Project:
        """The project once one of its items is removed: any anchor it held is unset; one more catalog change."""
        return replace(self, anchors=self.anchors.without(item_id)).revised()

    def with_offroad_speed(self, speed: OffroadSpeed) -> Project:
        """The project driving its tracks at `speed`: one more catalog change (earlier plan runs become Stale)."""
        return replace(self, offroad_speed=speed).revised()

    def with_settings(self, objective: Objective | None, speed: OffroadSpeed | None) -> Project:
        """The project with the settings given (`None` keeps one): one more catalog change when any differs, else the
        same project."""
        changed = replace(self, objective=objective or self.objective, offroad_speed=speed or self.offroad_speed)
        return self if changed == self else changed.revised()

"""A numbered plan run of a project (brief §8, §9). A job still running has no plan run. Pure domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PlanRunStatus = Literal["ready", "failed"]


@dataclass(frozen=True)
class PlanRun:
    id: str
    number: int
    status: PlanRunStatus

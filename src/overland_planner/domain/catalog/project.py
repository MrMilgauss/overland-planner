"""Trip project (brief §3) and its name rule (D151). Pure domain: standard library only (import-linter 2/5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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


@dataclass(frozen=True)
class Project:
    """A trip project. `revision` counts its changes (brief §3, stale detection); creation is change 1."""

    id: str
    name: ProjectName
    revision: int
    created_at: datetime

    @classmethod
    def create(cls, project_id: str, name: ProjectName, created_at: datetime) -> Project:
        return cls(id=project_id, name=name, revision=1, created_at=created_at)

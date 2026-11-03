"""What start-up does with the stored database revision (brief §7 step 3, D129, ADR-018, DV-5).

Pure decision table; the persistence adapter reads the revision read-only and executes the action:
no revision (fresh database) -> upgrade; at head -> nothing; an older revision of this planner -> pre-migration copy,
then upgrade; a revision this planner does not know (saved by a newer version) -> refuse, touching nothing.
Pre-migration copies are `planner-{rev}-{ts}.sqlite`; only the newest `KEPT_COPIES` survive a new copy.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

KEPT_COPIES = 3
_STAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"
_COPY_NAME = re.compile(r"^planner-(?P<revision>.+)-(?P<stamp>\d{8}T\d{12}Z)\.sqlite$")


class MigrationAction(StrEnum):
    REFUSE_NEWER = "refuse_newer"
    COPY_THEN_UPGRADE = "copy_then_upgrade"
    UPGRADE = "upgrade"
    NOTHING = "nothing"


@dataclass(frozen=True)
class RevisionChain:
    """The planner's own migration revisions, oldest first; the last one is the head."""

    revisions: tuple[str, ...]

    @classmethod
    def of(cls, revisions: Sequence[str]) -> RevisionChain:
        return cls(tuple(revisions))

    def action_for(self, stored: str | None) -> MigrationAction:
        if stored is None:
            return MigrationAction.UPGRADE
        if stored not in self.revisions:
            return MigrationAction.REFUSE_NEWER
        if stored == self.revisions[-1]:
            return MigrationAction.NOTHING
        return MigrationAction.COPY_THEN_UPGRADE


class PreMigrationCopies:
    """Names of the pre-migration copies in `db/backups` and which of them to delete after a new copy."""

    @staticmethod
    def name_for(revision: str, taken_at: datetime) -> str:
        return f"planner-{revision}-{taken_at.astimezone(UTC).strftime(_STAMP_FORMAT)}.sqlite"

    @staticmethod
    def to_prune(names: Iterable[str]) -> frozenset[str]:
        """Copies beyond the newest `KEPT_COPIES`; files that are not pre-migration copies are never pruned."""
        copies = sorted((match["stamp"], name) for name in names if (match := _COPY_NAME.match(name)))
        return frozenset(name for _, name in copies[:-KEPT_COPIES])

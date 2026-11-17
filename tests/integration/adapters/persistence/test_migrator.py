"""Stored revision vs this planner's migrations at start-up (brief §7 step 3, D129, ADR-018 pre-migration copy).

Integration level: single examples on a real SQLite file in a workspace data folder (never the OS temp folder,
ADR-011 D121). The decision table and copy retention are properties in tests/unit/application/platform/
test_migration_policy.py; these tests verify the adapter executes them: a newer database is left byte-identical
with no copy and no -wal/-shm side file; an older one is copied (newest three kept) and then upgraded; a fresh or
at-head database gets no copy.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.migrator import AlembicMigrator, DatabaseStartup
from overland_planner.application.ports.probe import ProbeResult
from tests.common.fakes import FakeClock
from tests.common.workspace import workspace_data_dir

REPO_ROOT = Path(__file__).resolve().parents[4]
MIGRATIONS = REPO_ROOT / "migrations"
HEAD = "0010"  # this planner's Alembic head
LATER = "9999"  # a no-op revision above any real head
STUB = """revision = "{revision}"
down_revision = "{down}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
"""


@pytest.fixture
def workspace() -> Iterator[Path]:
    with workspace_data_dir("integration") as data:
        yield data.parent


def _probe(data_dir: Path, migrations: Path = MIGRATIONS) -> ProbeResult:
    database = SqliteDatabase(data_dir)
    try:
        return DatabaseStartup(database, AlembicMigrator(database, migrations), FakeClock()).probe()
    finally:
        database.engine.dispose()


def _migrations_with_a_later_revision(workspace: Path, revision: str) -> Path:
    """The planner's migrations plus a no-op revision on top of head: 'the planner one version later'."""
    later = workspace / "later_migrations"
    shutil.copytree(MIGRATIONS, later, ignore=shutil.ignore_patterns("__pycache__"))
    (later / "versions" / f"{revision}_later.py").write_text(STUB.format(revision=revision, down=HEAD))
    return later


def _stored_revision(file: Path) -> str:
    with sqlite3.connect(file) as reader:
        revision = reader.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    reader.close()
    return str(revision)


def _folder_snapshot(folder: Path) -> dict[str, str]:
    return {
        str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def test_a_database_saved_by_a_newer_planner_is_refused_and_left_byte_identical(workspace: Path) -> None:
    data_dir = workspace / "data"
    later = _migrations_with_a_later_revision(workspace, "f0f0f0f0f0f0")
    assert _probe(data_dir, later) == ProbeResult(outcome="ok")
    before = _folder_snapshot(data_dir)

    assert _probe(data_dir) == ProbeResult(outcome="fatal", reason="db_newer_than_app")

    assert _folder_snapshot(data_dir) == before
    assert sorted(before) == ["db/planner.sqlite"]  # no copy, no -wal/-shm side file


def test_an_older_database_is_copied_then_upgraded_and_only_the_newest_three_copies_are_kept(workspace: Path) -> None:
    data_dir = workspace / "data"
    assert _probe(data_dir) == ProbeResult(outcome="ok")
    backups = data_dir / "db" / "backups"
    backups.mkdir()
    old_copies = [f"planner-{HEAD}-2026010{day}T000000000000Z.sqlite" for day in (1, 2, 3)]
    for name in old_copies:
        (backups / name).write_bytes(b"")

    assert _probe(data_dir, _migrations_with_a_later_revision(workspace, LATER)) == ProbeResult(outcome="ok")

    new_copy = f"planner-{HEAD}-20261102T193000000000Z.sqlite"  # FakeClock: 2026-11-02 19:30 UTC
    assert sorted(path.name for path in backups.iterdir()) == sorted([*old_copies[1:], new_copy])
    assert _stored_revision(backups / new_copy) == HEAD
    assert _stored_revision(data_dir / "db" / "planner.sqlite") == LATER


def test_a_fresh_database_and_one_at_head_get_no_copy(workspace: Path) -> None:
    data_dir = workspace / "data"

    assert _probe(data_dir) == ProbeResult(outcome="ok")
    assert _probe(data_dir) == ProbeResult(outcome="ok")

    assert not (data_dir / "db" / "backups").exists()
    assert _stored_revision(data_dir / "db" / "planner.sqlite") == HEAD

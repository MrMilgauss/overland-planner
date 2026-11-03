"""Alembic migrations from the repository (ADR-006, DV-5: every revision has a CI-tested downgrade; CI job 2 runs this).

Integration level: single examples on a real SQLite file in a workspace data folder, driven through the repository
`alembic.ini` like the operator's `alembic` command (D90).
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
STUB_REVISION = "f1f1f1f1f1f1"
HEAD_TABLES = {"projects", "items", "tracks", "pois"}


@pytest.fixture
def data_dir() -> Iterator[Path]:
    root = Path(os.environ.get("PLANNER_TEST_WORKSPACE", REPO_ROOT / ".data")) / "integration"
    folder = root / uuid.uuid4().hex[:12] / "data"
    (folder / "db").mkdir(parents=True)
    yield folder
    shutil.rmtree(folder.parent, ignore_errors=True)


def _config(url: str | None = None, extra_versions: Path | None = None) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    if url is not None:
        config.set_main_option("sqlalchemy.url", url)
    if extra_versions is not None:
        locations = [str(REPO_ROOT / "migrations" / "versions"), str(extra_versions)]
        config.set_main_option("version_locations", os.pathsep.join(locations))
    return config


def _tables(file: Path) -> set[str]:
    with sqlite3.connect(file) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    connection.close()
    return {name for (name,) in rows} - {"alembic_version"}


def _revision(file: Path) -> list[str]:
    with sqlite3.connect(file) as connection:
        rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    connection.close()
    return [version for (version,) in rows]


def test_upgrade_downgrade_to_base_and_upgrade_again_on_a_seeded_database(data_dir: Path) -> None:
    file = data_dir / "db" / "planner.sqlite"
    config = _config(f"sqlite:///{file}")
    head = ScriptDirectory.from_config(config).get_current_head()

    command.upgrade(config, "head")
    with sqlite3.connect(file) as seeded:
        seeded.execute(
            "INSERT INTO projects (id, name, objective, settings, revision, created_at) "
            "VALUES ('p1', 'Dolomiti 2028', 'balanced', '{}', 1, '2026-11-03 08:00:00')"
        )
    seeded.close()
    assert (_tables(file), _revision(file)) == (HEAD_TABLES, [head])

    command.downgrade(config, "base")
    assert (_tables(file), _revision(file)) == (set(), [])

    command.upgrade(config, "head")
    assert (_tables(file), _revision(file)) == (HEAD_TABLES, [head])


def test_downgrading_0002_drops_items_and_tracks_and_keeps_the_projects(data_dir: Path) -> None:
    file = data_dir / "db" / "planner.sqlite"
    config = _config(f"sqlite:///{file}")
    command.upgrade(config, "0002")
    with sqlite3.connect(file) as seeded:
        seeded.execute(
            "INSERT INTO projects (id, name, objective, settings, revision, created_at) "
            "VALUES ('p1', 'Alpi', 'distance', '{}', 2, '2026-11-03 08:00:00')"
        )
        seeded.execute(
            "INSERT INTO items (id, project_id, type, name, included, position) "
            "VALUES ('i1', 'p1', 'track', 'Assietta', 1, 1)"
        )
        seeded.execute(
            "INSERT INTO tracks (item_id, original_sha256, direction_version, canonical_sha256, point_count, "
            "entry_lat, entry_lon, exit_lat, exit_lon, length_m) VALUES ('i1', 'a', 1, 'b', 2, 45, 7, 45, 7, 1)"
        )
    seeded.close()

    command.downgrade(config, "0001")
    assert (_tables(file), _revision(file)) == ({"projects"}, ["0001"])
    with sqlite3.connect(file) as kept:
        assert kept.execute("SELECT id, name FROM projects").fetchall() == [("p1", "Alpi")]
    kept.close()

    command.upgrade(config, "0002")
    assert (_tables(file), _revision(file)) == ({"projects", "items", "tracks"}, ["0002"])


def test_downgrading_0003_drops_the_pois_and_keeps_projects_and_tracks(data_dir: Path) -> None:
    file = data_dir / "db" / "planner.sqlite"
    config = _config(f"sqlite:///{file}")
    command.upgrade(config, "0003")
    with sqlite3.connect(file) as seeded:
        seeded.execute(
            "INSERT INTO projects (id, name, objective, settings, revision, created_at) "
            "VALUES ('p1', 'Alpi', 'distance', '{}', 3, '2026-11-03 08:00:00')"
        )
        seeded.execute(
            "INSERT INTO items (id, project_id, type, name, included, position) VALUES "
            "('i1', 'p1', 'track', 'Assietta', 1, 1), ('i2', 'p1', 'poi', 'Briancon', 1, 2)"
        )
        seeded.execute(
            "INSERT INTO tracks (item_id, original_sha256, direction_version, canonical_sha256, point_count, "
            "entry_lat, entry_lon, exit_lat, exit_lon, length_m) VALUES ('i1', 'a', 1, 'b', 2, 45, 7, 45, 7, 1)"
        )
        seeded.execute("INSERT INTO pois (item_id, lat, lon) VALUES ('i2', 44.899, 6.643)")
    seeded.close()

    command.downgrade(config, "0002")
    assert (_tables(file), _revision(file)) == ({"projects", "items", "tracks"}, ["0002"])
    with sqlite3.connect(file) as kept:
        assert kept.execute("SELECT id, type FROM items").fetchall() == [("i1", "track")]
    kept.close()

    command.upgrade(config, "0003")
    assert (_tables(file), _revision(file)) == ({"projects", "items", "tracks", "pois"}, ["0003"])


def _project_columns(file: Path) -> set[str]:
    with sqlite3.connect(file) as connection:
        rows = connection.execute("PRAGMA table_info(projects)").fetchall()
    connection.close()
    return {row[1] for row in rows}


def test_downgrading_0004_drops_the_anchor_columns_and_keeps_projects_and_items(data_dir: Path) -> None:
    file = data_dir / "db" / "planner.sqlite"
    config = _config(f"sqlite:///{file}")
    command.upgrade(config, "0004")
    with sqlite3.connect(file) as seeded:
        seeded.execute(
            "INSERT INTO projects (id, name, objective, settings, revision, created_at) "
            "VALUES ('p1', 'Alpi', 'distance', '{}', 3, '2026-11-03 08:00:00')"
        )
        seeded.execute(
            "INSERT INTO items (id, project_id, type, name, included, position) "
            "VALUES ('i1', 'p1', 'poi', 'Casa', 1, 1)"
        )
        seeded.execute("INSERT INTO pois (item_id, lat, lon) VALUES ('i1', 45.0703, 7.6869)")
        seeded.execute("UPDATE projects SET start_item_id = 'i1', end_item_id = 'i1' WHERE id = 'p1'")
    seeded.close()

    command.downgrade(config, "0003")
    assert ({"start_item_id", "end_item_id"} & _project_columns(file), _revision(file)) == (set(), ["0003"])
    with sqlite3.connect(file) as kept:
        assert kept.execute("SELECT p.id, i.id FROM projects p JOIN items i ON i.project_id = p.id").fetchall() == [
            ("p1", "i1")
        ]
    kept.close()

    command.upgrade(config, "0004")
    assert ({"start_item_id", "end_item_id"} <= _project_columns(file), _revision(file)) == (True, ["0004"])


def test_an_external_url_and_extra_version_locations_are_honoured(data_dir: Path, tmp_path: Path) -> None:
    head = ScriptDirectory.from_config(_config()).get_current_head()
    (tmp_path / f"{STUB_REVISION}_later.py").write_text(
        f'revision = "{STUB_REVISION}"\ndown_revision = "{head}"\nbranch_labels = None\ndepends_on = None\n\n\n'
        "def upgrade() -> None:\n    pass\n\n\ndef downgrade() -> None:\n    pass\n"
    )
    file = data_dir / "db" / "elsewhere.sqlite"

    command.upgrade(_config(f"sqlite:///{file}", extra_versions=tmp_path), "heads")

    assert _revision(file) == [STUB_REVISION]


def test_without_a_url_alembic_uses_the_database_under_data_dir(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    command.upgrade(_config(), "head")

    assert _tables(data_dir / "db" / "planner.sqlite") == HEAD_TABLES

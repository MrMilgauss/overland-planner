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
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from overland_planner.adapters.persistence.database import SqliteDatabase, database_file

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


def _seed_trip_at_head(file: Path) -> None:
    with sqlite3.connect(file) as seeded:
        seeded.execute(
            "INSERT INTO projects (id, name, objective, settings, revision, created_at) "
            "VALUES ('p1', 'Alpi', 'distance', '{}', 4, '2026-11-03 08:00:00')"
        )
        seeded.execute(
            "INSERT INTO items (id, project_id, type, name, included, position) VALUES "
            "('i1', 'p1', 'track', 'Assietta', 1, 1), ('i2', 'p1', 'poi', 'Casa', 1, 2)"
        )
        seeded.execute(
            "INSERT INTO tracks (item_id, original_sha256, direction_version, canonical_sha256, point_count, "
            "entry_lat, entry_lon, exit_lat, exit_lon, length_m) VALUES ('i1', 'a', 1, 'b', 2, 45, 7, 45, 7, 1)"
        )
        seeded.execute("INSERT INTO pois (item_id, lat, lon) VALUES ('i2', 45.0703, 7.6869)")
        seeded.execute("UPDATE projects SET start_item_id = 'i2', end_item_id = 'i2' WHERE id = 'p1'")
    seeded.close()


def _trip(file: Path) -> dict[str, list[tuple[str, ...]]]:
    with sqlite3.connect(file) as connection:
        trip = {
            table: connection.execute(f"SELECT {key} FROM {table} ORDER BY 1").fetchall()  # noqa: S608 - fixed names
            for table, key in (("projects", "id"), ("items", "id, type"), ("tracks", "item_id"), ("pois", "item_id"))
        }
    connection.close()
    return trip


SEEDED_TRIP = {"projects": [("p1",)], "items": [("i1", "track"), ("i2", "poi")], "tracks": [("i1",)], "pois": [("i2",)]}


def _downgrade_through_the_operator_path(config: Config, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # `docker compose run --rm planner alembic downgrade 0003` (D90): no URL on the Config, the database under DATA_DIR.
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    command.downgrade(_config(), "0003")


def _downgrade_on_a_connection_with_foreign_keys_on(config: Config, data_dir: Path, _mp: pytest.MonkeyPatch) -> None:
    # The planner's own connection (WAL, foreign_keys=ON), handed over to env.py as at start-up.
    database = SqliteDatabase(data_dir)
    try:
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            config.attributes["connection"] = connection
            command.downgrade(config, "0003")
            connection.commit()
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1, "enforcement is restored"
    finally:
        config.attributes.pop("connection", None)
        database.engine.dispose()


@pytest.mark.parametrize(
    "downgrade",
    [_downgrade_through_the_operator_path, _downgrade_on_a_connection_with_foreign_keys_on],
    ids=["operator-path", "foreign-keys-on"],
)
def test_downgrading_0004_never_cascades_to_the_items_of_a_project_with_anchors(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, downgrade: Any
) -> None:
    # Regression (03-09): the 0004 downgrade rebuilds `projects`; with foreign_keys=ON the rebuild's DROP TABLE would
    # cascade-delete every item, so the downgrade switches foreign keys off around the rebuild.
    file = database_file(data_dir)
    config = _config(f"sqlite:///{file}")
    command.upgrade(config, "head")
    _seed_trip_at_head(file)

    downgrade(config, data_dir, monkeypatch)

    assert (_trip(file), _revision(file)) == (SEEDED_TRIP, ["0003"])
    assert {"start_item_id", "end_item_id"} & _project_columns(file) == set()
    with sqlite3.connect(file) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


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

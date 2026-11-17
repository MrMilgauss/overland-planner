"""Alembic migrations from the repository (ADR-006, DV-5: every revision has a CI-tested downgrade; CI job 2 runs this).

Integration level: single examples on a real SQLite file in a workspace data folder, driven through the repository
`alembic.ini` like the operator's `alembic` command (D90).
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from overland_planner.adapters.persistence.database import SqliteDatabase, database_file
from overland_planner.adapters.persistence.migrator import AlembicMigrator, DatabaseStartup
from overland_planner.adapters.persistence.planning_unit_of_work import SqlAlchemyPlanningUnitOfWork
from overland_planner.application.ports.probe import ProbeResult
from tests.common.catalog_fakes import RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.workspace import workspace_data_dir

REPO_ROOT = Path(__file__).resolve().parents[3]
STUB_REVISION = "f1f1f1f1f1f1"
TABLES_OF_0006 = {"projects", "items", "tracks", "pois", "plan_runs"}
TABLES_OF_0007 = TABLES_OF_0006 | {"plan_job_log"}
HEAD_TABLES = TABLES_OF_0007 | {"plan_refusals"}


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        (folder / "db").mkdir()
        yield folder


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


def _columns(file: Path, table: str) -> set[str]:
    with sqlite3.connect(file) as connection:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
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
    assert ({"start_item_id", "end_item_id"} & _columns(file, "projects"), _revision(file)) == (set(), ["0003"])
    with sqlite3.connect(file) as kept:
        assert kept.execute("SELECT p.id, i.id FROM projects p JOIN items i ON i.project_id = p.id").fetchall() == [
            ("p1", "i1")
        ]
    kept.close()

    command.upgrade(config, "0004")
    assert ({"start_item_id", "end_item_id"} <= _columns(file, "projects"), _revision(file)) == (True, ["0004"])


_INSERT_PLAN_RUN = (
    "INSERT INTO plan_runs (id, project_id, number, status, created_at, revision, provider_id, objective, inputs) "
    "VALUES (?, ?, ?, 'ready', '2026-11-04 08:00:00', 4, 'mock', 'distance', '{}')"
)


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
        seeded.execute(_INSERT_PLAN_RUN, ("r1", "p1", 1))
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


def _downgrade_through_the_operator_path(
    config: Config, data_dir: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    # `docker compose run --rm planner alembic downgrade <target>` (D90): no URL on the Config, the database under
    # DATA_DIR.
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    command.downgrade(_config(), target)


def _downgrade_on_a_connection_with_foreign_keys_on(
    config: Config, data_dir: Path, _mp: pytest.MonkeyPatch, target: str
) -> None:
    # The planner's own connection (WAL, foreign_keys=ON), handed over to env.py as at start-up.
    database = SqliteDatabase(data_dir)
    try:
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            config.attributes["connection"] = connection
            command.downgrade(config, target)
            connection.commit()
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1, "enforcement is restored"
    finally:
        config.attributes.pop("connection", None)
        database.engine.dispose()


BOTH_DOWNGRADE_PATHS = pytest.mark.parametrize(
    "downgrade",
    [_downgrade_through_the_operator_path, _downgrade_on_a_connection_with_foreign_keys_on],
    ids=["operator-path", "foreign-keys-on"],
)


@BOTH_DOWNGRADE_PATHS
def test_downgrading_0004_never_cascades_to_the_items_of_a_project_with_anchors(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, downgrade: Any
) -> None:
    # Regression (03-09): the 0004 downgrade rebuilds `projects`; with foreign_keys=ON the rebuild's DROP TABLE would
    # cascade-delete every item, so the downgrade switches foreign keys off around the rebuild.
    file = database_file(data_dir)
    config = _config(f"sqlite:///{file}")
    command.upgrade(config, "head")
    assert _tables(file) == HEAD_TABLES
    _seed_trip_at_head(file)

    downgrade(config, data_dir, monkeypatch, "0003")

    assert (_trip(file), _revision(file)) == (SEEDED_TRIP, ["0003"])
    assert {"start_item_id", "end_item_id"} & _columns(file, "projects") == set()
    with sqlite3.connect(file) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


@BOTH_DOWNGRADE_PATHS
def test_downgrading_0005_drops_the_plan_runs_and_keeps_every_project_and_item(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, downgrade: Any
) -> None:
    file = database_file(data_dir)
    config = _config(f"sqlite:///{file}")
    command.upgrade(config, "head")
    assert _tables(file) == HEAD_TABLES
    _seed_trip_at_head(file)

    downgrade(config, data_dir, monkeypatch, "0004")

    assert (_trip(file), _revision(file)) == (SEEDED_TRIP, ["0004"])
    assert _tables(file) == TABLES_OF_0006 - {"plan_runs"}
    assert {"start_item_id", "end_item_id"} <= _columns(file, "projects"), "the anchors stay at 0004"

    command.upgrade(config, "0005")
    assert (_trip(file), _tables(file), _revision(file)) == (SEEDED_TRIP, TABLES_OF_0006, ["0005"])


RUN_COLUMNS_OF_0006 = {"totals", "report", "fingerprint", "memo_hit"}


def _plan_runs(file: Path) -> list[tuple[Any, ...]]:
    with sqlite3.connect(file) as connection:
        rows = connection.execute("SELECT id, project_id, number, status, inputs FROM plan_runs ORDER BY 1").fetchall()
    connection.close()
    return rows


SEEDED_RUNS = [("r1", "p1", 1, "ready", "{}")]


@BOTH_DOWNGRADE_PATHS
def test_0006_keeps_every_run_stored_before_it_with_no_totals_and_its_downgrade_keeps_them_too(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, downgrade: Any
) -> None:
    file = database_file(data_dir)
    config = _config(f"sqlite:///{file}")
    command.upgrade(config, "0005")
    _seed_trip_at_head(file)

    command.upgrade(config, "0006")
    assert (_trip(file), _plan_runs(file), _revision(file)) == (SEEDED_TRIP, SEEDED_RUNS, ["0006"])
    assert _columns(file, "plan_runs") >= RUN_COLUMNS_OF_0006, f"plan_runs has {sorted(_columns(file, 'plan_runs'))}"
    with sqlite3.connect(file) as connection:
        added = connection.execute("SELECT totals, report, fingerprint, memo_hit FROM plan_runs").fetchall()
    connection.close()
    assert added == [(None, None, None, 0)]  # read through the repository at the head: the 0008 test

    downgrade(config, data_dir, monkeypatch, "0005")

    assert (_trip(file), _plan_runs(file), _revision(file)) == (SEEDED_TRIP, SEEDED_RUNS, ["0005"])
    assert RUN_COLUMNS_OF_0006 & _columns(file, "plan_runs") == set()
    with sqlite3.connect(file) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()

    command.upgrade(config, "0006")
    assert (_plan_runs(file), _revision(file)) == (SEEDED_RUNS, ["0006"])
    assert _columns(file, "plan_runs") >= RUN_COLUMNS_OF_0006


SEEDED_JOB_ROW = (
    "INSERT INTO plan_job_log (job_id, project_id, started_at, ended_at, terminal_state, plan_run_id, memo_hit, "
    "ignore_memo, app_version, elapsed_ms) VALUES ('j1', 'p1', '2026-11-09 07:00:00', '2026-11-09 07:00:42', 'done', "
    "'r1', 0, 0, 'dev', 42000)"
)


@BOTH_DOWNGRADE_PATHS
def test_0007_adds_the_plan_job_log_and_its_round_trip_keeps_every_project_item_and_run(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, downgrade: Any
) -> None:
    file = database_file(data_dir)
    config = _config(f"sqlite:///{file}")
    command.upgrade(config, "0006")
    _seed_trip_at_head(file)

    command.upgrade(config, "0007")
    assert (_trip(file), _plan_runs(file), _tables(file), _revision(file)) == (
        SEEDED_TRIP,
        SEEDED_RUNS,
        TABLES_OF_0007,
        ["0007"],
    )
    with sqlite3.connect(file) as connection:
        connection.execute(SEEDED_JOB_ROW)
    connection.close()

    downgrade(config, data_dir, monkeypatch, "0006")
    assert (_trip(file), _plan_runs(file), _tables(file), _revision(file)) == (
        SEEDED_TRIP,
        SEEDED_RUNS,
        TABLES_OF_0006,
        ["0006"],
    )

    command.upgrade(config, "0007")
    assert (_trip(file), _plan_runs(file), _tables(file), _revision(file)) == (
        SEEDED_TRIP,
        SEEDED_RUNS,
        TABLES_OF_0007,
        ["0007"],
    )
    with sqlite3.connect(file) as connection:
        assert connection.execute("SELECT count(*) FROM plan_job_log").fetchone() == (0,), "the log starts empty"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_a_0006_release_refuses_a_0007_database(data_dir: Path, tmp_path: Path) -> None:
    file = database_file(data_dir)
    command.upgrade(_config(f"sqlite:///{file}"), "0007")
    release_0006 = data_dir.parent / "migrations_0006"
    shutil.copytree(
        REPO_ROOT / "migrations",
        release_0006,
        ignore=shutil.ignore_patterns("__pycache__", "0007_*.py", "0008_*.py", "0009_*.py"),
    )
    database = SqliteDatabase(data_dir)
    try:
        refused = DatabaseStartup(database, AlembicMigrator(database, release_0006), FakeClock()).probe()
    finally:
        database.engine.dispose()

    assert refused == ProbeResult(outcome="fatal", reason="db_newer_than_app")
    assert _revision(file) == ["0007"]


RUN_COLUMNS_OF_0008 = {"reproducible", "not_fully_optimised", "run_time_ms", "memo_source_run_id"}


@BOTH_DOWNGRADE_PATHS
def test_0008_adds_the_run_flags_older_runs_read_reproducible_with_no_label_and_its_downgrade_keeps_every_run(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, downgrade: Any
) -> None:
    file = database_file(data_dir)
    config = _config(f"sqlite:///{file}")
    command.upgrade(config, "0007")
    _seed_trip_at_head(file)

    command.upgrade(config, "0008")
    assert (_trip(file), _plan_runs(file), _revision(file)) == (SEEDED_TRIP, SEEDED_RUNS, ["0008"])
    assert _columns(file, "plan_runs") >= RUN_COLUMNS_OF_0008, f"plan_runs has {sorted(_columns(file, 'plan_runs'))}"
    with sqlite3.connect(file) as connection:
        added = connection.execute(
            "SELECT reproducible, not_fully_optimised, run_time_ms, memo_source_run_id FROM plan_runs"
        ).fetchall()
    connection.close()
    assert added == [(1, None, None, None)]
    database = SqliteDatabase(data_dir)
    try:
        with SqlAlchemyPlanningUnitOfWork(database, RecordingEventLog()) as uow:
            shown, listed = uow.plan_runs.get("r1"), uow.plan_runs.list("p1")
    finally:
        database.engine.dispose()
    assert shown is not None
    assert (shown.id, shown.project_id, shown.totals) == ("r1", "p1", None)  # stored before 0006: no totals
    assert (shown.reproducible, shown.not_fully_optimised) == (True, None)
    assert [(run.id, run.reproducible, run.not_fully_optimised) for run in listed] == [("r1", True, None)]

    downgrade(config, data_dir, monkeypatch, "0007")
    assert (_trip(file), _plan_runs(file), _tables(file), _revision(file)) == (
        SEEDED_TRIP,
        SEEDED_RUNS,
        TABLES_OF_0007,
        ["0007"],
    )
    assert RUN_COLUMNS_OF_0008 & _columns(file, "plan_runs") == set()
    with sqlite3.connect(file) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()

    command.upgrade(config, "0008")
    assert (_plan_runs(file), _revision(file)) == (SEEDED_RUNS, ["0008"])
    assert _columns(file, "plan_runs") >= RUN_COLUMNS_OF_0008


@BOTH_DOWNGRADE_PATHS
def test_0009_adds_the_empty_plan_refusals_and_its_downgrade_drops_only_them(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, downgrade: Any
) -> None:
    file = database_file(data_dir)
    config = _config(f"sqlite:///{file}")
    command.upgrade(config, "0008")
    _seed_trip_at_head(file)

    command.upgrade(config, "0009")
    assert (_trip(file), _plan_runs(file), _tables(file), _revision(file)) == (
        SEEDED_TRIP,
        SEEDED_RUNS,
        HEAD_TABLES,
        ["0009"],
    )
    assert _columns(file, "plan_refusals") == {"id", "created_at", "project_id", "reason", "http_status"}
    with sqlite3.connect(file) as connection:
        assert connection.execute("SELECT count(*) FROM plan_refusals").fetchone() == (0,), "the table starts empty"
        connection.execute(
            "INSERT INTO plan_refusals (created_at, project_id, reason, http_status) "
            "VALUES ('2026-11-09 07:00:00', 'p1', 'routing_engine_not_ready', 503)"
        )
    connection.close()

    downgrade(config, data_dir, monkeypatch, "0008")
    assert (_trip(file), _plan_runs(file), _tables(file), _revision(file)) == (
        SEEDED_TRIP,
        SEEDED_RUNS,
        TABLES_OF_0007,
        ["0008"],
    )

    command.upgrade(config, "0009")
    assert (_tables(file), _revision(file)) == (HEAD_TABLES, ["0009"])


def test_plan_runs_are_numbered_once_per_project_and_go_with_their_project(data_dir: Path) -> None:
    file = database_file(data_dir)
    command.upgrade(_config(f"sqlite:///{file}"), "head")
    assert _tables(file) == HEAD_TABLES
    _seed_trip_at_head(file)

    with sqlite3.connect(file) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError, match=r"plan_runs\.project_id, plan_runs\.number"):
            connection.execute(_INSERT_PLAN_RUN, ("r2", "p1", 1))
        connection.execute("DELETE FROM projects WHERE id = 'p1'")
        assert connection.execute("SELECT count(*) FROM plan_runs").fetchone() == (0,)
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

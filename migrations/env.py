"""Alembic environment of the planner (ADR-006).

Database, in this order: a connection handed over by the planner (`config.attributes["connection"]`, used at start-up
so the planner's PRAGMAs and writer lock apply); else `sqlalchemy.url` when set on the Config (tests, tooling);
else the planner's database under DATA_DIR (`docker compose run --rm planner alembic downgrade ...`, D90).
`version_locations` and `path_separator` come from the Config as given.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import Connection, create_engine

from overland_planner.adapters.persistence.database import database_url
from overland_planner.adapters.persistence.tables import metadata
from overland_planner.bootstrap.settings import Settings

config = context.config


def _url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return database_url(Settings.from_environ(os.environ).data_dir)


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    handed_over = config.attributes.get("connection")
    if handed_over is not None:
        _run(handed_over)
        return
    engine = create_engine(_url())
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()

"""Table definitions (SQLAlchemy Core) - the schema at the Alembic head, for repositories and autogenerate.

Each schema change ships as its own Alembic revision with a tested downgrade (DV-5); this module mirrors the head.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, Table, Text

metadata = MetaData()

projects = Table(
    "projects",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("objective", Text, nullable=False),
    Column("settings", JSON, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

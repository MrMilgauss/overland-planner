"""Table definitions (SQLAlchemy Core) - the schema at the Alembic head, for repositories and autogenerate.

Each schema change ships as its own Alembic revision with a tested downgrade (DV-5); this module mirrors the head.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    false,
)

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
    # The trip's Start and End POIs (HC-2, brief §9); cleared when the item goes. `use_alter`: items reference projects.
    Column("start_item_id", Text, ForeignKey("items.id", ondelete="SET NULL", use_alter=True), nullable=True),
    Column("end_item_id", Text, ForeignKey("items.id", ondelete="SET NULL", use_alter=True), nullable=True),
)

# One row per catalog item (brief §9); `position` keeps the order items were added within their project.
items = Table(
    "items",
    metadata,
    Column("id", Text, primary_key=True),
    Column("project_id", Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("type", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("included", Boolean, nullable=False),
    Column("notes", Text, nullable=True),
    Column("position", Integer, nullable=False),
)

# The track details of a `track` item (brief §9, ADR-018): hashes address files/originals/{original_sha256}.gpx and
# files/tracks/{item_id}/canonical.v{direction_version}.json. Elevation totals are filled by a later slice.
tracks = Table(
    "tracks",
    metadata,
    Column("item_id", Text, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("description", Text, nullable=True),
    Column("original_sha256", Text, nullable=False),
    Column("direction_version", Integer, nullable=False),
    Column("canonical_sha256", Text, nullable=False),
    Column("point_count", Integer, nullable=False),
    Column("entry_lat", Float, nullable=False),
    Column("entry_lon", Float, nullable=False),
    Column("exit_lat", Float, nullable=False),
    Column("exit_lon", Float, nullable=False),
    Column("length_m", Float, nullable=False),
    Column("elevation_gain_m", Float, nullable=True),
    Column("elevation_loss_m", Float, nullable=True),
)

# The location of a `poi` item (brief §9), decimal degrees as added (US-02c).
pois = Table(
    "pois",
    metadata,
    Column("item_id", Text, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("lat", Float, nullable=False),
    Column("lon", Float, nullable=False),
)

# One row per numbered plan run (brief §9); a job still running has none. `totals` is NULL for a Failed run and for one
# stored before 0006; `report` is NULL for a ready run and for one stored before 05-08; `fingerprint` is NULL for a run
# stored before the memo (05-10) and `memo_hit` false.
plan_runs = Table(
    "plan_runs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("project_id", Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("failure_reason", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("provider_id", Text, nullable=False),
    Column("objective", Text, nullable=False),
    Column("inputs", JSON, nullable=False),
    Column("itinerary", JSON, nullable=True),
    Column("totals", JSON, nullable=True),
    Column("report", JSON, nullable=True),
    Column("fingerprint", Text, nullable=True),
    Column("memo_hit", Boolean, nullable=False, server_default=false()),
    UniqueConstraint("project_id", "number", name="uq_plan_runs_project_id_number"),
)

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
    true,
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
# stored before the memo (05-10) and `memo_hit` false. The run flags (0008): `reproducible` (true for a run stored
# before), `not_fully_optimised` (time_limit, stopped, optimizer_failed or NULL), `run_time_ms` and `memo_source_run_id`
# (NULL until 06-10 writes them).
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
    Column("reproducible", Boolean, nullable=False, server_default=true()),
    Column("not_fully_optimised", Text, nullable=True),
    Column("run_time_ms", Integer, nullable=True),
    Column("memo_source_run_id", Text, nullable=True),
    Column("profile", Text, nullable=True),
    UniqueConstraint("project_id", "number", name="uq_plan_runs_project_id_number"),
)

# One append-only row per plan job that reached its end (ADR-015 DV-2, D93; 0007): the values of its
# `plan.job.finished` line plus start, end, `solver_wait_s` and `app_version`. Fields owned by later slices are NULL.
# No foreign key: the log outlives a deleted project or run.
plan_job_log = Table(
    "plan_job_log",
    metadata,
    Column("job_id", Text, primary_key=True),
    Column("project_id", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("ended_at", DateTime(timezone=True), nullable=False),
    Column("terminal_state", Text, nullable=False),
    Column("memo_hit", Boolean, nullable=False),
    Column("ignore_memo", Boolean, nullable=False),
    Column("app_version", Text, nullable=False),
    Column("elapsed_ms", Integer, nullable=False),
    Column("plan_run_id", Text, nullable=True),
    Column("items_included", Integer, nullable=True),
    Column("legs_total", Integer, nullable=True),
    Column("legs_new", Integer, nullable=True),
    Column("legs_cached", Integer, nullable=True),
    Column("points_new", Integer, nullable=True),
    Column("second_pass_pairs", Integer, nullable=True),
    Column("retried", Boolean, nullable=True),
    Column("stage_ms", JSON, nullable=True),
    Column("solver_solutions", Integer, nullable=True),
    Column("incumbents", Integer, nullable=True),
    Column("reproducible", Boolean, nullable=True),
    Column("not_fully_optimised_reason", Text, nullable=True),
    Column("unconfirmed_legs", Integer, nullable=True),
    Column("retraces", Integer, nullable=True),
    Column("solver_wait_s", Float, nullable=True),
    Column("provider_id", Text, nullable=True),
    Column("error_class", Text, nullable=True),
    Column("reason", Text, nullable=True),
)

# One append-only row per refused plan request (ADR-013 Amendment 4, D248; 0009). No foreign key: it outlives a project.
plan_refusals = Table(
    "plan_refusals",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("project_id", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("http_status", Integer, nullable=False),
)

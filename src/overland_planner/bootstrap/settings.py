"""Planner settings from the process environment (brief section 12 `.env` keys), validated at start-up (brief §7.1).

The only source is the mapping given to `Settings.from_environ`; the composition root passes `os.environ` in
production. Keys are case-sensitive; keys the planner does not read are ignored. An invalid value is fatal.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
# Only the mock provider exists until slice 06a wires Valhalla.
RoutingProvider = Literal["mock"]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REPO_WEB_DIST = _REPO_ROOT / "web" / "dist"
# The planner's Alembic migrations; the image sets MIGRATIONS_DIR=/app/migrations.
_REPO_MIGRATIONS = _REPO_ROOT / "migrations"


class InvalidSettingsError(ValueError):
    """One or more settings are outside their domain; the message names each offending key."""

    def __init__(self, problems: Mapping[str, str]) -> None:
        self.setting_names = frozenset(problems)
        details = "; ".join(f"{key}: {problem}" for key, problem in sorted(problems.items()))
        super().__init__(f"invalid settings: {details}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    data_dir: Annotated[Path, Field(validation_alias="DATA_DIR")] = Path("/data")
    log_level: Annotated[LogLevel, Field(validation_alias="LOG_LEVEL")] = "INFO"
    routing_provider: Annotated[RoutingProvider, Field(validation_alias="ROUTING_PROVIDER")] = "mock"
    solver_budget: Annotated[int, Field(validation_alias="SOLVER_BUDGET", gt=0)] = 10_000
    planner_git_sha: Annotated[str, Field(validation_alias="PLANNER_GIT_SHA", min_length=1)] = "dev"
    web_dist_dir: Annotated[Path, Field(validation_alias="WEB_DIST_DIR")] = _REPO_WEB_DIST
    migrations_dir: Annotated[Path, Field(validation_alias="MIGRATIONS_DIR")] = _REPO_MIGRATIONS

    @field_validator("data_dir", "web_dist_dir", "migrations_dir", mode="before")
    @classmethod
    def _path_not_empty(cls, value: object) -> object:
        if value == "":
            raise ValueError("must not be empty")
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> Settings:
        values: dict[str, Any] = dict(environ)  # raw text; pydantic converts and validates each field
        try:
            return cls(**values)
        except ValidationError as error:
            raise InvalidSettingsError(
                {str(problem["loc"][0]): problem["msg"] for problem in error.errors(include_url=False)}
            ) from None

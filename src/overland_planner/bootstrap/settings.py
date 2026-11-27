"""Planner settings from the process environment (brief section 12 `.env` keys), validated at start-up (brief §7.1).

The only source is the mapping given to `Settings.from_environ`; the composition root passes `os.environ` in
production. Keys are case-sensitive; keys the planner does not read are ignored. An invalid value is fatal.
The shared household password (PLANNER_BASIC_AUTH_USER / _PASSWORD, brief §12) is set as a pair or not at all; an
empty value counts as unset (a `KEY=` line). The password is a `SecretStr`, so no repr or error message shows it.
The upload caps (MAX_UPLOAD_FILE_MB, MAX_UPLOAD_REQUEST_MB in MiB, MAX_UPLOAD_FILES) must be positive (ADR-011 Am. 1);
an empty cap (compose passes `${MAX_UPLOAD_...:-}`) is its default.
MOCK_PLAN is the path of the offline road map's script (brief sections 6 and 12); empty or absent means no script. The
composition root reads and validates the file once at start-up; a bad file refuses the start for `routing_provider`.
FEASIBILITY_LIMIT_S and OPTIMISATION_LIMIT_S (ADR-014 section 2) are whole seconds above 0, written in ASCII digits;
the feasibility limit may not exceed the optimisation limit (D116), else the start is refused naming
FEASIBILITY_LIMIT_S.
ROUTING_PROVIDER is `mock` (default) or `valhalla`; the engine's keys (ADR-013 Amendment 4, D247) are VALHALLA_URL (http
or https with a host), VALHALLA_EXPECTED_VERSION, VALHALLA_MAX_MATRIX_PAIRS (1 or more), VALHALLA_CONCURRENCY (1 to 8)
and CONFIRMED_SNAP_M (above 0); an empty value is the default. MOCK_PLAN with `valhalla` refuses the start.
The map's tiles (ADR-004, ADR-003 Amendment 2) are MAP_TILE_URL (http or https with a host and the placeholders {z},
{x} and {y}; userinfo, a fragment, or a query parameter whose name contains key, token, secret, sig, auth, apikey,
api_key, appid, app_id, password, pwd, access or client_id refuses the start, naming the part and never its value,
D256; a key hidden in a path segment cannot be told from a tile path and is not detected: use a provider without a
key), MAP_TILE_ATTRIBUTION and MAP_TILE_MAX_ZOOM (1 to 22); an empty value is
the default.
The light base map (ADR-004 Amendment 1, D287) is MAP_BASE_STYLE_URL, a style address (http or https with a host;
no placeholders are required) under the same guard as MAP_TILE_URL, so a key in its path is not detected either, and
MAP_BASE_ATTRIBUTION, its credit; empty or blank is the default. A query word without "=" that names a private
parameter refuses the start without naming the word, since it may itself be the secret.
The served road map (slice 12c, D301, D314): ROAD_MAP_DIR is the tileset folder of the volume the planner mounts read-
only, ROAD_MAP_CHANGES_DIR the folder of the rebuild's notes (`progress.txt`); empty or absent means unknown. With the
offline road map, ROAD_MAP_SERVED_TILESET names the tileset folder it serves; with `valhalla` a value refuses the start.
GEOFABRIK_INDEX_URL (an http or https address with a host; empty means the public Geofabrik index) is the free list of
regions the owner searches; its origin is the only one region downloads may come from (D306, D313).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import unquote_plus, urlsplit

from pydantic import Field, SecretStr, ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from overland_planner.application.ports.tour_solver import DEFAULT_FEASIBILITY_LIMIT_S, DEFAULT_OPTIMISATION_LIMIT_S

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
RoutingProvider = Literal["mock", "valhalla"]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REPO_WEB_DIST = _REPO_ROOT / "web" / "dist"
# The planner's Alembic migrations; the image sets MIGRATIONS_DIR=/app/migrations.
_REPO_MIGRATIONS = _REPO_ROOT / "migrations"
_WHOLE_SECONDS = re.compile(r"[0-9]+")
_TILE_PLACEHOLDERS = ("{z}", "{x}", "{y}")
_PRIVATE_PARAMETER_WORDS = (
    *("key", "token", "secret", "signature", "sig", "auth", "apikey", "api_key", "appid", "app_id"),
    *("password", "pwd", "access", "client_id"),
)


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
    max_upload_file_mb: Annotated[int, Field(validation_alias="MAX_UPLOAD_FILE_MB", gt=0)] = 25
    max_upload_request_mb: Annotated[int, Field(validation_alias="MAX_UPLOAD_REQUEST_MB", gt=0)] = 100
    max_upload_files: Annotated[int, Field(validation_alias="MAX_UPLOAD_FILES", gt=0)] = 50
    basic_auth_user: Annotated[str | None, Field(validation_alias="PLANNER_BASIC_AUTH_USER")] = None
    basic_auth_password: Annotated[SecretStr | None, Field(validation_alias="PLANNER_BASIC_AUTH_PASSWORD")] = None
    mock_plan: Annotated[Path | None, Field(validation_alias="MOCK_PLAN")] = None
    feasibility_limit_s: Annotated[int, Field(validation_alias="FEASIBILITY_LIMIT_S", gt=0)] = (
        DEFAULT_FEASIBILITY_LIMIT_S
    )
    optimisation_limit_s: Annotated[int, Field(validation_alias="OPTIMISATION_LIMIT_S", gt=0)] = (
        DEFAULT_OPTIMISATION_LIMIT_S
    )

    valhalla_url: Annotated[str, Field(validation_alias="VALHALLA_URL")] = "http://valhalla:8002"
    valhalla_expected_version: Annotated[str, Field(validation_alias="VALHALLA_EXPECTED_VERSION")] = "3.9.1"
    valhalla_max_matrix_pairs: Annotated[int, Field(validation_alias="VALHALLA_MAX_MATRIX_PAIRS", ge=1)] = 2500
    valhalla_concurrency: Annotated[int, Field(validation_alias="VALHALLA_CONCURRENCY", ge=1, le=8)] = 2
    confirmed_snap_m: Annotated[int, Field(validation_alias="CONFIRMED_SNAP_M", gt=0)] = 250

    map_tile_url: Annotated[str, Field(validation_alias="MAP_TILE_URL")] = (
        "https://tile.opentopomap.org/{z}/{x}/{y}.png"
    )
    map_tile_attribution: Annotated[str, Field(validation_alias="MAP_TILE_ATTRIBUTION")] = (
        "Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)"
    )
    map_tile_max_zoom: Annotated[int, Field(validation_alias="MAP_TILE_MAX_ZOOM", ge=1, le=22)] = 17
    map_base_style_url: Annotated[str, Field(validation_alias="MAP_BASE_STYLE_URL")] = (
        "https://tiles.openfreemap.org/styles/positron"
    )
    map_base_attribution: Annotated[str, Field(validation_alias="MAP_BASE_ATTRIBUTION")] = (
        "© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors"
    )
    # Place search (slice 12c, D307, D314): the Add menu's "Search for a place". The address is only parsed here;
    # empty means the public Nominatim default (usage policy: https://operations.osmfoundation.org/policies/nominatim/).
    place_search: Annotated[Literal["on", "off"], Field(validation_alias="PLACE_SEARCH")] = "on"
    place_search_url: Annotated[str, Field(validation_alias="PLACE_SEARCH_URL")] = (
        "https://nominatim.openstreetmap.org/search"
    )

    # The free list of regions the road map is built from (slice 12c, D306): Geofabrik's index, normally left unset. The
    # downloads the planner may ask about are under this address's own origin, so tests run against a local server.
    geofabrik_index_url: Annotated[str, Field(validation_alias="GEOFABRIK_INDEX_URL")] = (
        "https://download.geofabrik.de/index-v1-nogeom.json"
    )

    road_map_dir: Annotated[Path | None, Field(validation_alias="ROAD_MAP_DIR")] = None
    road_map_changes_dir: Annotated[Path | None, Field(validation_alias="ROAD_MAP_CHANGES_DIR")] = None
    road_map_served_tileset: Annotated[str | None, Field(validation_alias="ROAD_MAP_SERVED_TILESET")] = None

    @field_validator("map_tile_url")
    @classmethod
    def _tile_url_without_private_parameter(cls, value: str) -> str:
        cls._http_url_with_host(value)
        if any(placeholder not in value for placeholder in _TILE_PLACEHOLDERS):
            raise ValueError("must contain {z}, {x} and {y}")
        return cls._without_private_parts(value)

    @field_validator("map_base_style_url")
    @classmethod
    def _style_url_without_private_parameter(cls, value: str) -> str:
        cls._http_url_with_host(value)
        return cls._without_private_parts(value)

    @staticmethod
    def _without_private_parts(value: str) -> str:
        parts = urlsplit(value)
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            raise ValueError("carries userinfo")
        if parts.fragment or "#" in value:
            raise ValueError("carries a fragment")
        for pair in parts.query.split("&"):
            name, equals, _ = pair.partition("=")
            name = unquote_plus(name)
            if any(word in name.lower() for word in _PRIVATE_PARAMETER_WORDS):
                if not equals:  # a bare word may itself be the secret: refuse without naming it
                    raise ValueError("carries a private parameter")
                raise ValueError(f"carries the private parameter {name}")  # the name only, never the value (D256)
        return value

    @field_validator("valhalla_url", "geofabrik_index_url")
    @classmethod
    def _http_url_with_host(cls, value: str) -> str:
        try:
            parts = urlsplit(value)
            usable = parts.scheme in ("http", "https") and bool(parts.hostname)
        except ValueError:
            usable = False
        if not usable:
            raise ValueError("must be an http or https URL with a host")
        return value

    @field_validator(
        "basic_auth_user",
        "basic_auth_password",
        "mock_plan",
        "road_map_dir",
        "road_map_changes_dir",
        "road_map_served_tileset",
        mode="before",
    )
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("map_base_style_url", "map_base_attribution", mode="before")
    @classmethod
    def _blank_base_map_is_default(cls, value: object, info: ValidationInfo) -> object:
        blank = isinstance(value, str) and value.strip() == ""
        return cls.model_fields[str(info.field_name)].default if blank else value

    @field_validator(
        "max_upload_file_mb",
        "max_upload_request_mb",
        "max_upload_files",
        "valhalla_url",
        "valhalla_expected_version",
        "valhalla_max_matrix_pairs",
        "valhalla_concurrency",
        "confirmed_snap_m",
        "map_tile_url",
        "map_tile_attribution",
        "map_tile_max_zoom",
        "place_search",
        "place_search_url",
        "geofabrik_index_url",
        mode="before",
    )
    @classmethod
    def _empty_cap_is_default(cls, value: object, info: ValidationInfo) -> object:
        return cls.model_fields[str(info.field_name)].default if value == "" else value

    @field_validator("feasibility_limit_s", "optimisation_limit_s", mode="before")
    @classmethod
    def _whole_seconds(cls, value: object) -> object:
        if isinstance(value, str) and _WHOLE_SECONDS.fullmatch(value) is None:
            raise ValueError("must be a whole number of seconds above 0")
        return value

    @field_validator("basic_auth_user")
    @classmethod
    def _user_without_colon(cls, value: str | None) -> str | None:
        if value is not None and ":" in value:
            raise ValueError("must not contain ':' (HTTP Basic credentials end the user name at the first colon)")
        return value

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
            settings = cls(**values)
        except ValidationError as error:
            raise InvalidSettingsError(
                {str(problem["loc"][0]): problem["msg"] for problem in error.errors(include_url=False)}
            ) from None
        if (settings.basic_auth_user is None) != (settings.basic_auth_password is None):
            missing = "PLANNER_BASIC_AUTH_USER" if settings.basic_auth_user is None else "PLANNER_BASIC_AUTH_PASSWORD"
            raise InvalidSettingsError({missing: "must be set together with the other shared password setting"})
        if settings.feasibility_limit_s > settings.optimisation_limit_s:
            raise InvalidSettingsError({"FEASIBILITY_LIMIT_S": "must not exceed OPTIMISATION_LIMIT_S (D116)"})
        if settings.routing_provider == "valhalla" and settings.mock_plan is not None:
            raise InvalidSettingsError({"MOCK_PLAN": "cannot be used with ROUTING_PROVIDER=valhalla (offline script)"})
        if settings.routing_provider == "valhalla" and settings.road_map_served_tileset is not None:
            raise InvalidSettingsError(
                {"ROAD_MAP_SERVED_TILESET": "cannot be used with ROUTING_PROVIDER=valhalla (the engine names it)"}
            )
        return settings

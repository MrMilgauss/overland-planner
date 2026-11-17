"""Static contract of the home-server compose set-up (slice 00b, step 02-04; D81, D82, D83, D167, D173, D174).

deploy/compose.yaml, deploy/compose.ci.yaml and .env.example are read as data. The running container's hardening is
proven in CI job 7 (tests/deploy/test_container_hardening.py); `docker compose config` refusing to start without
PLANNER_BIND is proven here whenever Docker is available (CI job 7, -m compose), and skips on a Mac without Docker.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from overland_planner.bootstrap.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "deploy" / "compose.yaml"
COMPOSE_CI = REPO_ROOT / "deploy" / "compose.ci.yaml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
FAIL_CLOSED_PORTS = "${PLANNER_BIND:?PLANNER_BIND must be set in .env}:${PLANNER_PORT:-8080}:8080"
INTERPOLATION = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?P<rest>[^}]*)\}")
SECRET_SETTINGS = ("PLANNER_BASIC_AUTH_PASSWORD",)
UPLOAD_CAPS = ("MAX_UPLOAD_FILE_MB", "MAX_UPLOAD_REQUEST_MB", "MAX_UPLOAD_FILES")  # ADR-011 Am. 1
ENGINE_SETTINGS = ("VALHALLA_EXPECTED_VERSION", "VALHALLA_MAX_MATRIX_PAIRS", "VALHALLA_CONCURRENCY", "CONFIRMED_SNAP_M")
MAP_TILE_SETTINGS = ("MAP_TILE_URL", "MAP_TILE_ATTRIBUTION", "MAP_TILE_MAX_ZOOM")  # ADR-004
LIMITS = {"FEASIBILITY_LIMIT_S": "feasibility_limit_s", "OPTIMISATION_LIMIT_S": "optimisation_limit_s"}  # ADR-014
HARDENING = (
    "image",
    "init",
    "cpus",
    "mem_limit",
    "memswap_limit",
    "pids_limit",
    "oom_score_adj",
    "cap_drop",
    "security_opt",
    "read_only",
    "tmpfs",
    "healthcheck",
    "logging",
)
PERF_VOLUMES = {"planner-perf-data": {"name": "overland_planner-perf-data"}}
VALHALLA_VOLUMES = {"valhalla-data": {"name": "overland_valhalla-data"}}
VALHALLA_IMAGE = (
    "${VALHALLA_IMAGE:-ghcr.io/valhalla/valhalla-scripted:3.9.1-arm64"
    "@sha256:f182f45e9e71cbe737e6c394d68808c67a7bd12e2a4cc47c4aba864de77ecdc6}"
)
VALHALLA_ENVIRONMENT = {
    "serve_tiles": "True",
    "use_tiles_ignore_pbf": "True",
    "force_rebuild": "False",
    "server_threads": "2",
    "update_existing_config": "False",
    "build_admins": "False",
    "build_time_zones": "False",
    "build_elevation": "False",
    "build_transit": "False",
}


TUNNEL_IMAGE = "alpine/socat:1.8.0.3@sha256:beb4a68d9e4fe6b0f21ea774a0fde6c31f580dde6368939ed70100c5385b015e"
FETCH_IMAGE = "debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc"
BUILD_ENVIRONMENT = {
    "build_admins": "True",
    "build_time_zones": "True",
    "build_elevation": "False",
    "build_transit": "False",
    "serve_tiles": "False",
    "force_rebuild": "True",
    "server_threads": "3",
}
LOG_10M = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "2"}}


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader that keeps compose merge tags (`!override`, `!reset`) as plain values."""


def _tagged(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_ComposeLoader.add_multi_constructor("!", _tagged)


def _load(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} missing"
    loaded = yaml.load(path.read_text(), Loader=_ComposeLoader)  # noqa: S506 - SafeLoader subclass
    assert isinstance(loaded, dict), f"{path.name} is not a mapping"
    return loaded


def _planner() -> dict[str, Any]:
    planner: dict[str, Any] = _load(COMPOSE)["services"]["planner"]
    return planner


def _env_example() -> dict[str, str]:
    """KEY=value lines of .env.example, commented-out documentation lines (`# KEY=value`) included."""
    assert ENV_EXAMPLE.is_file(), ".env.example missing"
    pairs = re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=(.*)$", ENV_EXAMPLE.read_text(), re.MULTILINE)
    return {key: value.strip() for key, value in pairs}


def test_only_the_planner_is_published_on_the_fail_closed_home_address() -> None:
    compose = _load(COMPOSE)
    planner = compose["services"]["planner"]

    assert compose["name"] == "overland"
    assert set(compose["services"]) == {
        "planner",
        "planner-perf",
        "valhalla",
        "valhalla-build",
        "valhalla-fetch",
        "valhalla-tunnel",
    }
    assert "profiles" not in planner, "the default profile starts the planner"
    assert planner["ports"] == [FAIL_CLOSED_PORTS], "PLANNER_BIND has no default: compose refuses to start without it"
    assert planner["networks"] == ["edge", "routing"] and set(compose["networks"]) == {"edge", "routing", "egress"}
    assert "depends_on" not in planner, "the planner never depends on the routing engine (D234)"
    assert planner["image"].startswith("${PLANNER_IMAGE:?"), "the image comes from release.env (deploy.sh)"
    assert "build" not in planner, "the Pi runs the published image, never a local build"


def test_planner_runs_capped_and_hardened() -> None:
    planner = _planner()

    assert {key: planner.get(key) for key in ("cpus", "mem_limit", "memswap_limit", "pids_limit", "oom_score_adj")} == {
        "cpus": 1,
        "mem_limit": "1g",
        "memswap_limit": "1g",
        "pids_limit": 256,
        "oom_score_adj": 500,
    }
    assert planner["cap_drop"] == ["ALL"] and "cap_add" not in planner
    assert planner["security_opt"] == ["no-new-privileges:true"]
    assert planner["read_only"] is True
    assert planner["tmpfs"] == ["/tmp:size=64m,mode=1777"]  # noqa: S108 - path inside the container
    assert (planner["init"], planner["restart"]) == (True, "unless-stopped")
    assert "privileged" not in planner and "user" not in planner, "the image's uid 10001 is kept"


def test_data_volume_log_rotation_and_curl_free_healthcheck() -> None:
    compose = _load(COMPOSE)
    planner = compose["services"]["planner"]

    assert planner["volumes"] == ["planner-data:/data"]
    assert compose["volumes"] == {"planner-data": {"name": "overland_planner-data"}} | PERF_VOLUMES | VALHALLA_VOLUMES
    assert planner["logging"] == {"driver": "json-file", "options": {"max-size": "10m", "max-file": "5"}}
    probe = " ".join(planner["healthcheck"]["test"])
    assert "/healthz" in probe and "curl" not in probe and planner["healthcheck"]["test"][0] == "CMD"


def test_settings_reach_the_container_by_interpolation_and_secrets_are_never_written_down() -> None:
    environment: dict[str, str] = _planner()["environment"]

    # Empty when unset; the planner reads an empty value as its default (shared password off, caps 25/100/50).
    for key in ("PLANNER_BASIC_AUTH_USER", "PLANNER_BASIC_AUTH_PASSWORD", *UPLOAD_CAPS):
        assert environment[key] == f"${{{key}:-}}", f"{key} is interpolated from .env, empty when unset"
    assert environment["DATA_DIR"] == "/data"
    # D247: the road map is chosen by .env (mock when unset); the engine is the compose service, its tuning is empty
    # (the planner's default) unless .env says otherwise.
    assert environment["ROUTING_PROVIDER"] == "${ROUTING_PROVIDER:-mock}"
    assert environment["VALHALLA_URL"] == "http://valhalla:8002"
    for key in ENGINE_SETTINGS:
        assert environment[key] == f"${{{key}:-}}", f"{key} is interpolated from .env, empty when unset"
    for key in MAP_TILE_SETTINGS:  # ADR-004: the map tiles come from .env, empty (the OpenTopoMap default) when unset
        assert environment[key] == f"${{{key}:-}}", f"{key} is interpolated from .env, empty when unset"
    # The solve limits pass through with the planner's own defaults (ADR-014 section 2, brief section 12).
    for key, field in LIMITS.items():
        default = Settings.model_fields[field].default
        assert environment[key] == f"${{{key}:-{default}}}", f"{key} is interpolated from .env, {default} when unset"
    for path in (COMPOSE, COMPOSE_CI, ENV_EXAMPLE):
        assert "env_file" not in path.read_text(), f"{path.name}: settings come through interpolation only"
    example = _env_example()
    assert [key for key in SECRET_SETTINGS if example.get(key, "")] == [], ".env.example carries no secret value"


def test_env_example_documents_every_setting_and_binds_loopback() -> None:
    example = _env_example()
    planner_settings = {str(field.validation_alias) for field in Settings.model_fields.values()}
    compose_variables = {m["name"] for path in (COMPOSE, COMPOSE_CI) for m in INTERPOLATION.finditer(path.read_text())}

    assert example.get("PLANNER_BIND") == "127.0.0.1"
    assert sorted((planner_settings | compose_variables) - set(example)) == []


def test_ci_override_runs_the_loaded_image_on_loopback_only() -> None:
    planner = _load(COMPOSE_CI)["services"]["planner"]

    assert "image" not in planner, "compose.yaml is interpolated first: the CI image comes from PLANNER_IMAGE"
    assert planner["pull_policy"] == "never"
    assert planner["ports"] == ["127.0.0.1:8080:8080"]
    assert re.search(r"^\s*ports:\s*!override\b", COMPOSE_CI.read_text(), re.MULTILINE), "replaces, not appends"


def test_planner_perf_runs_the_planners_image_hardened_on_its_own_volume_and_loopback_only() -> None:
    # bypass: a compose file is one document; this is a single-example wiring check (D164, D167, D173).
    compose = _load(COMPOSE)
    planner, perf = compose["services"]["planner"], compose["services"]["planner-perf"]

    assert perf["profiles"] == ["perf"], "only `--profile perf` starts planner-perf"
    assert {key: perf.get(key) for key in HARDENING} == {key: planner.get(key) for key in HARDENING}
    assert perf["ports"] == ["127.0.0.1:18080:8080"], "reached only through the ssh tunnel of make perf-pi"
    assert perf["networks"] == ["edge", "routing"]
    assert perf["volumes"] == ["planner-perf-data:/data", "./perf:/perf:ro"]
    assert "overland_planner-data" not in str(perf) and "planner-data:" not in str(perf["volumes"])
    assert planner["environment"]["ROUTING_PROVIDER"] == "${ROUTING_PROVIDER:-mock}", "the household switch is .env"
    assert perf["environment"] == planner["environment"] | {
        "MOCK_PLAN": "${PERF_MOCK_PLAN:-}",
        "ROUTING_PROVIDER": "${PERF_ROUTING_PROVIDER:-mock}",  # D236: perf-pi MODE=e2e and acceptance-pi say valhalla
        "VALHALLA_URL": "http://valhalla:8002",
    }
    assert perf.get("restart", "no") == "no", "a measurement planner never comes back by itself"


def test_valhalla_tunnel_forwards_the_engine_to_the_pis_loopback_only_for_make_contract_live() -> None:
    # bypass: a compose file is one document; this is a single-example contract check (D164, D235).
    compose = _load(COMPOSE)
    tunnel, valhalla = compose["services"]["valhalla-tunnel"], compose["services"]["valhalla"]

    assert tunnel["image"] == TUNNEL_IMAGE and tunnel["profiles"] == ["ops"]
    assert tunnel["command"] == "TCP-LISTEN:8002,fork,reuseaddr TCP:valhalla:8002"
    assert tunnel["ports"] == ["127.0.0.1:18002:8002"] and tunnel["networks"] == ["edge", "routing"]
    assert (tunnel["restart"], tunnel["cap_drop"], tunnel["security_opt"]) == (
        "no",
        ["ALL"],
        ["no-new-privileges:true"],
    )
    assert (tunnel["read_only"], tunnel["mem_limit"]) == (True, "64m")
    assert "ports" not in valhalla and "expose" not in valhalla, "valhalla itself is never published"
    assert "ops" not in valhalla["profiles"] and "depends_on" not in tunnel


def test_valhalla_serves_a_seeded_tileset_capped_hardened_and_never_published() -> None:
    # bypass: a compose file is one document; this is a single-example contract check (ADR-013 Amendment 3, D234).
    valhalla = _load(COMPOSE)["services"]["valhalla"]

    assert valhalla["image"] == VALHALLA_IMAGE and valhalla["profiles"] == ["routing"]
    assert valhalla["networks"] == ["routing"] and "ports" not in valhalla and "expose" not in valhalla
    assert valhalla["environment"] == VALHALLA_ENVIRONMENT
    assert {
        key: valhalla.get(key) for key in ("cpus", "mem_limit", "memswap_limit", "oom_score_adj", "pids_limit")
    } == {
        "cpus": 2,
        "mem_limit": "4g",
        "memswap_limit": "4g",
        "oom_score_adj": 500,
        "pids_limit": 512,
    }
    assert (valhalla["restart"], valhalla["security_opt"]) == ("unless-stopped", ["no-new-privileges:true"])
    assert valhalla["logging"] == {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}
    assert valhalla["healthcheck"] == {
        "test": ["CMD", "curl", "-fsS", "http://127.0.0.1:8002/status"],
        "interval": "30s",
        "timeout": "5s",
        "retries": 3,
        "start_period": "120s",
        "start_interval": "2s",
    }
    assert valhalla["volumes"] == [
        {
            "type": "volume",
            "source": "valhalla-data",
            "target": "/custom_files",
            "volume": {"subpath": "tilesets/${VALHALLA_TILESET:-none}"},
        }
    ]
    assert "privileged" not in valhalla and "cap_add" not in valhalla


def _subpath_mount(service: dict[str, Any], target: str) -> list[dict[str, Any]]:
    return [{"type": "volume", "source": "valhalla-data", "target": target, "volume": {"subpath": "build"}}]


def test_valhalla_build_runs_offline_capped_and_only_on_demand() -> None:
    build = _load(COMPOSE)["services"]["valhalla-build"]

    assert build["image"] == VALHALLA_IMAGE and build["profiles"] == ["valhalla-build"]
    assert build["network_mode"] == "none" and "networks" not in build and "ports" not in build
    assert build["environment"] == BUILD_ENVIRONMENT
    assert build["volumes"] == _subpath_mount(build, "/custom_files")
    assert (build["cpus"], build["mem_limit"], build["memswap_limit"]) == (
        3,
        "${VALHALLA_BUILD_MEM:-9g}",
        "${VALHALLA_BUILD_MEM:-9g}",
    )
    assert (build["oom_score_adj"], build["restart"], build["logging"]) == (500, "no", LOG_10M)


def test_valhalla_fetch_is_the_only_service_on_egress_and_publishes_nothing() -> None:
    compose = _load(COMPOSE)
    fetch = compose["services"]["valhalla-fetch"]

    assert fetch["image"] == FETCH_IMAGE and fetch["profiles"] == ["valhalla-build"]
    assert fetch["networks"] == ["egress"] and "ports" not in fetch and "network_mode" not in fetch
    assert fetch["volumes"] == _subpath_mount(fetch, "/work")
    assert (fetch["cpus"], fetch["mem_limit"], fetch["memswap_limit"]) == (2, "6g", "6g")
    assert (fetch["oom_score_adj"], fetch["restart"], fetch["logging"]) == (500, "no", LOG_10M)
    assert compose["networks"]["egress"] in ({}, None, {"driver": "bridge"})
    assert [n for n, s in compose["services"].items() if "egress" in s.get("networks", [])] == ["valhalla-fetch"]


@pytest.mark.parametrize("service", ["valhalla-build", "valhalla-fetch"])
def test_neither_default_start_nor_the_routing_profile_includes_the_tile_build(service: str) -> None:
    services = _load(COMPOSE)["services"]

    assert [n for n, s in services.items() if "profiles" not in s] == ["planner"]
    assert "routing" not in services[service]["profiles"]


def test_the_config_overrides_hold_exactly_the_two_adr_013_deltas() -> None:
    overrides = json.loads((REPO_ROOT / "deploy/valhalla/valhalla.overrides.json").read_text())

    assert overrides == {
        "thor": {"costmatrix": {"allow_second_pass": True}},
        "service_limits": {"auto": {"max_matrix_distance": 2000000}},
    }


def test_the_routing_network_is_internal_and_only_the_planners_publish_a_port() -> None:
    compose = _load(COMPOSE)
    services = compose["services"]

    assert compose["networks"]["routing"] == {"internal": True}
    assert sorted(name for name, service in services.items() if "ports" in service) == [
        "planner",
        "planner-perf",
        "valhalla-tunnel",
    ]
    assert [name for name, service in services.items() if "profiles" not in service] == ["planner"]
    assert [name for name, service in services.items() if "routing" in service.get("networks", [])] == [
        "planner",
        "planner-perf",
        "valhalla",
        "valhalla-tunnel",
    ]


def test_the_serving_services_stay_within_the_pi_memory_budget() -> None:
    services = _load(COMPOSE)["services"]
    gib = {"g": 1}

    serving = [services["planner"], services["valhalla"]]  # planner-perf is a measurement profile, never co-running
    total = sum(int(s["mem_limit"][:-1]) * gib[s["mem_limit"][-1]] for s in serving)

    assert total <= 5, "planner 1g + valhalla 4g leave room for the Pi's OS (D83)"


@pytest.mark.compose
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker is not available on this host")
def test_valhalla_parses_without_a_tileset_and_only_the_planner_starts_without_a_profile() -> None:
    env = os.environ | {"PLANNER_IMAGE": "overland-planner:unused", "PLANNER_BIND": "127.0.0.1"}
    env.pop("VALHALLA_TILESET", None)
    base = ["docker", "compose", "-p", "overland", "--env-file", os.devnull, "-f", str(COMPOSE)]

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([*base, *args], env=env, capture_output=True, text=True, timeout=60, check=False)

    config = run("--profile", "routing", "config", "--quiet")
    services = run("config", "--services")

    assert config.returncode == 0, config.stderr
    assert services.returncode == 0, services.stderr
    assert services.stdout.split() == ["planner"]


@pytest.mark.compose
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker is not available on this host")
def test_the_perf_profile_adds_only_planner_perf() -> None:
    env = os.environ | {"PLANNER_IMAGE": "overland-planner:unused", "PLANNER_BIND": "127.0.0.1"}
    base = ["docker", "compose", "-p", "overland", "--env-file", os.devnull, "-f", str(COMPOSE)]

    def services(*profile: str) -> list[str]:
        done = subprocess.run(
            [*base, *profile, "config", "--services"], env=env, capture_output=True, text=True, timeout=60, check=False
        )
        assert done.returncode == 0, done.stderr
        return sorted(done.stdout.split())

    assert services() == ["planner"]
    assert services("--profile", "perf") == ["planner", "planner-perf"]


@pytest.mark.compose
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker is not available on this host")
def test_compose_refuses_to_start_without_planner_bind() -> None:
    env = {k: v for k, v in os.environ.items() if k != "PLANNER_BIND"} | {"PLANNER_IMAGE": "overland-planner:unused"}
    command = ["docker", "compose", "--env-file", os.devnull, "-f", str(COMPOSE), "config", "--quiet"]

    refused = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60, check=False)
    accepted = subprocess.run(
        command, env=env | {"PLANNER_BIND": "127.0.0.1"}, capture_output=True, text=True, timeout=60, check=False
    )

    assert refused.returncode != 0 and "PLANNER_BIND must be set in .env" in refused.stderr
    assert accepted.returncode == 0, accepted.stderr

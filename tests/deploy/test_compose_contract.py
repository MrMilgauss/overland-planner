"""Static contract of the home-server compose set-up (slice 00b, step 02-04; D81, D82, D83, D167, D173, D174).

deploy/compose.yaml, deploy/compose.ci.yaml and .env.example are read as data. The running container's hardening is
proven in CI job 7 (tests/deploy/test_container_hardening.py); `docker compose config` refusing to start without
PLANNER_BIND is proven here whenever Docker is available (CI job 7, -m compose), and skips on a Mac without Docker.
"""

from __future__ import annotations

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
    assert set(compose["services"]) == {"planner"}
    assert planner["ports"] == [FAIL_CLOSED_PORTS], "PLANNER_BIND has no default: compose refuses to start without it"
    assert planner["networks"] == ["edge"] and set(compose["networks"]) == {"edge"}
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
    assert compose["volumes"] == {"planner-data": {"name": "overland_planner-data"}}
    assert planner["logging"] == {"driver": "json-file", "options": {"max-size": "10m", "max-file": "5"}}
    probe = " ".join(planner["healthcheck"]["test"])
    assert "/healthz" in probe and "curl" not in probe and planner["healthcheck"]["test"][0] == "CMD"


def test_settings_reach_the_container_by_interpolation_and_secrets_are_never_written_down() -> None:
    environment: dict[str, str] = _planner()["environment"]

    for key in ("PLANNER_BASIC_AUTH_USER", "PLANNER_BASIC_AUTH_PASSWORD"):
        assert environment[key] == f"${{{key}:-}}", f"{key} is interpolated from .env, empty when unset"
    assert environment["DATA_DIR"] == "/data" and environment["ROUTING_PROVIDER"] == "mock"
    for path in (COMPOSE, COMPOSE_CI, ENV_EXAMPLE):
        assert "env_file" not in path.read_text(), f"{path.name}: settings come through interpolation only"
    example = _env_example()
    assert [key for key in SECRET_SETTINGS if example.get(key, "")] == [], ".env.example carries no secret value"


def test_env_example_documents_every_setting_and_binds_loopback() -> None:
    example = _env_example()
    planner_settings = {str(field.validation_alias) for field in Settings.model_fields.values()}
    compose_variables = {m["name"] for path in (COMPOSE, COMPOSE_CI) for m in INTERPOLATION.finditer(path.read_text())}

    assert example.get("PLANNER_BIND") == "127.0.0.1"
    assert sorted((planner_settings | compose_variables) - {"GITHUB_SHA"} - set(example)) == []


def test_ci_override_runs_the_loaded_image_on_loopback_only() -> None:
    planner = _load(COMPOSE_CI)["services"]["planner"]

    assert planner["image"] == "overland-planner:ci-${GITHUB_SHA:?GITHUB_SHA names the loaded CI image}"
    assert planner["pull_policy"] == "never"
    assert planner["ports"] == ["127.0.0.1:8080:8080"]
    assert re.search(r"^\s*ports:\s*!override\b", COMPOSE_CI.read_text(), re.MULTILINE), "replaces, not appends"


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

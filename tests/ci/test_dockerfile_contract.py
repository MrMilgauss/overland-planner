"""Static contract of the planner image (slice 00a, D84/D85/D170/D173/D176).

The real builds (amd64 native, arm64 via QEMU) run in CI jobs 5 and 6; the read-only-root run in job 7. Here the
Dockerfile and .dockerignore are read as text and every criterion of step 01-06 is checked against the instructions.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\b")


@dataclass(frozen=True)
class Instruction:
    stage: int
    keyword: str
    args: str


def _instructions() -> list[Instruction]:
    assert DOCKERFILE.is_file(), "Dockerfile missing at the repository root"
    logical = re.sub(r"\\\n", " ", DOCKERFILE.read_text())
    result: list[Instruction] = []
    stage = -1
    for raw in logical.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keyword, _, args = line.partition(" ")
        keyword = keyword.upper()
        if keyword == "FROM":
            stage += 1
        result.append(Instruction(stage, keyword, " ".join(args.split())))
    return result


def _of(keyword: str, stage: int | None = None) -> list[Instruction]:
    return [i for i in _instructions() if i.keyword == keyword and (stage is None or i.stage == stage)]


def _final_stage() -> int:
    return _of("FROM")[-1].stage


def _labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    for instruction in _of("LABEL", _final_stage()):
        for key, value in re.findall(r'([\w.\-]+)=("[^"]*"|\S+)', instruction.args):
            labels[key] = value.strip('"')
    return labels


def test_node_stage_runs_on_buildplatform() -> None:
    node_stages = [i for i in _of("FROM") if "node:22-bookworm-slim" in i.args]
    assert len(node_stages) == 1, "exactly one node:22-bookworm-slim stage expected"
    node = node_stages[0]
    assert "--platform=$BUILDPLATFORM" in node.args
    runs = " && ".join(i.args for i in _of("RUN", node.stage))
    assert "npm ci" in runs and "vite build" in runs
    final = _final_stage()
    assert node.stage != final
    assert any("web/dist" in i.args and "--from=" in i.args for i in _of("COPY", final)), "runtime lacks web/dist"


def test_runtime_ships_the_migrations_and_alembic_ini() -> None:
    final = _final_stage()
    copies = [i.args for i in _of("COPY", final)]
    assert "migrations /app/migrations" in copies, "runtime lacks the Alembic migrations"
    assert "alembic.ini /app/alembic.ini" in copies, "runtime lacks alembic.ini (D90 downgrade path)"
    assert any("MIGRATIONS_DIR=/app/migrations" in i.args for i in _of("ENV", final))


def test_python_installed_with_uv_sync_frozen_no_dev() -> None:
    syncs = [i for i in _of("RUN") if "uv sync" in i.args]
    assert syncs, "no uv sync in any stage"
    for sync in syncs:
        assert "--frozen" in sync.args and "--no-dev" in sync.args, sync.args
    final = _final_stage()
    assert all(sync.stage != final for sync in syncs), "uv must run in the builder, not in the runtime"
    assert not any("astral-sh/uv" in i.args for i in _of("COPY", final)), "uv binary leaked into the runtime"
    images = {next(tok for tok in i.args.split() if not tok.startswith("--")) for i in _of("FROM")}
    python_bases = {ref for ref in images if ref.startswith("python:")}
    assert len(python_bases) == 1, f"builder and runtime must share one python base, got {python_bases}"


def test_bytecode_is_precompiled() -> None:
    builder_env = " ".join(i.args for i in _of("ENV") if i.stage != _final_stage())
    assert re.search(r"\bUV_COMPILE_BYTECODE=1\b", builder_env), "UV_COMPILE_BYTECODE=1 missing in the builder"


def test_base_images_and_uv_are_pinned_by_digest() -> None:
    stage_names = {m.group(1) for i in _of("FROM") if (m := re.search(r"\bAS\s+(\S+)", i.args, re.IGNORECASE))}
    for instruction in _of("FROM"):
        image = next(tok for tok in instruction.args.split() if not tok.startswith("--"))
        if image in stage_names:
            continue
        assert DIGEST.search(image), f"base image not pinned by digest: {image}"
    uv_copies = [i for i in _of("COPY") if "ghcr.io/astral-sh/uv" in i.args]
    assert uv_copies, "uv is not copied from ghcr.io/astral-sh/uv"
    for copy in uv_copies:
        assert DIGEST.search(copy.args), f"uv image not pinned by digest: {copy.args}"


def test_runtime_user_is_10001() -> None:
    final = _final_stage()
    users = _of("USER", final)
    assert users and users[-1].args.split(":")[0] == "10001"
    runs = " ".join(i.args for i in _of("RUN", final))
    assert re.search(r"useradd\b.*--uid 10001", runs) or re.search(r"useradd\b.*-u 10001", runs)
    assert re.search(r"chown\s+(-R\s+)?10001(:10001)?\s+/data\b", runs), "/data must be owned by 10001"
    env = " ".join(i.args for i in _of("ENV", final))
    assert "DATA_DIR=/data" in env


def test_no_volume_is_declared() -> None:
    assert _of("VOLUME") == []


def test_oci_labels_are_set() -> None:
    labels = _labels()
    expected = {
        "org.opencontainers.image.revision": "${GIT_SHA}",
        "org.opencontainers.image.source": "https://github.com/MrMilgauss/overland-planner",
        "org.opencontainers.image.created": "${COMMIT_TS}",
        "org.overland.alembic-head": "${ALEMBIC_HEAD}",
        "org.overland.commit-ts": "${COMMIT_TS}",
    }
    assert {k: labels.get(k) for k in expected} == expected
    final_args = {i.args.split("=")[0] for i in _of("ARG", _final_stage())}
    assert {"GIT_SHA", "COMMIT_TS", "ALEMBIC_HEAD"} <= final_args
    assert any("PLANNER_GIT_SHA=${GIT_SHA}" in i.args for i in _of("ENV", _final_stage()))


@pytest.mark.parametrize(
    "path",
    [
        ".git/config",
        ".data/dev/planner.db",
        ".env",
        ".env.production",
        "web/node_modules/vite/index.js",
        "tests/ci/test_dockerfile_contract.py",
        "docs/feature/x.md",
        "export.gpx",
        "web/public/sample.gpx",
        ".venv/bin/python",
        "web/dist/index.html",
        "mutants/x.py",
    ],
)
def test_dockerignore_excludes_secrets_data_and_gpx(path: str) -> None:
    assert DOCKERIGNORE.is_file(), ".dockerignore missing at the repository root"
    excluded = False
    for raw in DOCKERIGNORE.read_text().splitlines():
        rule = raw.strip()
        if not rule or rule.startswith("#"):
            continue
        negate = rule.startswith("!")
        pattern = rule.lstrip("!").strip("/").removeprefix("**/")
        parts = path.split("/")
        prefixes = ["/".join(parts[: n + 1]) for n in range(len(parts))]
        hit = any(fnmatch.fnmatch(p, pattern) for p in prefixes) or (
            rule.lstrip("!").startswith("**/") and any(fnmatch.fnmatch(seg, pattern) for seg in parts)
        )
        if hit:
            excluded = not negate
    assert excluded, f"{path} would enter the build context"


def test_healthcheck_targets_healthz() -> None:
    checks = _of("HEALTHCHECK", _final_stage())
    assert len(checks) == 1
    check = checks[0].args
    for option in ("--interval=30s", "--retries=3", "--start-period=30s"):
        assert option in check
    assert "python" in check and "urllib" in check and "http://127.0.0.1:8080/healthz" in check
    assert "curl" not in check and "wget" not in check
    cmd = " ".join(i.args for i in _of("CMD", _final_stage()))
    for token in ("uvicorn", "--factory", "overland_planner.bootstrap.app_factory:create_app", "--port", "8080"):
        assert token in cmd
    assert re.search(r'"--workers",\s*"1"', cmd)

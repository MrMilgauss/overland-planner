"""The hardened planner container writes only /data and /tmp (D173), run in CI job 7 (-m "compose or security").

Starts a one-shot planner container from deploy/compose.yaml with the image under test (PLANNER_IMAGE) in a project
of its own, with the data volume renamed so a real `overland_planner-data` volume is never touched or removed.
Needs Docker and --run-external; skips on the Mac.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "deploy" / "compose.yaml"
PROJECT = "overland-hardening-check"
CANDIDATES = ("/app", "/app/.venv", "/", "/etc", "/usr/local/lib", "/var", "/home", "/data", "/tmp")  # noqa: S108 - paths inside the container
PROBE = f"""
import json, os, uuid
writable = []
for folder in {CANDIDATES!r}:
    path = os.path.join(folder, ".write-probe-" + uuid.uuid4().hex)
    try:
        with open(path, "w") as handle:
            handle.write("x")
    except OSError:
        continue
    os.remove(path)
    writable.append(folder)
status = dict(line.split(":", 1) for line in open("/proc/self/status") if ":" in line)
print(json.dumps({{"writable": writable, "uid": os.getuid(), "cap_eff": status["CapEff"].strip(),
                   "no_new_privs": status["NoNewPrivs"].strip()}}))
"""

pytestmark = [pytest.mark.security, pytest.mark.requires_external]


@pytest.fixture
def compose_command(tmp_path: Path) -> list[str]:
    if shutil.which("docker") is None:
        pytest.skip("Docker is not available on this host")
    if not os.environ.get("PLANNER_IMAGE"):
        pytest.skip("set PLANNER_IMAGE to the image under test")
    isolated_volume = tmp_path / "compose.hardening.yaml"
    isolated_volume.write_text(f"volumes:\n  planner-data:\n    name: {PROJECT}_data\n")
    return ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE), "-f", str(isolated_volume)]


def test_planner_container_writes_only_data_and_tmp_without_privileges(compose_command: list[str]) -> None:
    env = {**os.environ, "PLANNER_BIND": "127.0.0.1"}
    try:
        run = subprocess.run(
            [*compose_command, "run", "--rm", "--no-deps", "-T", "planner", "python", "-c", PROBE],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    finally:
        subprocess.run([*compose_command, "down", "-v"], env=env, capture_output=True, timeout=120, check=False)
    assert run.returncode == 0, run.stderr[-2000:]
    report = json.loads(run.stdout.strip().splitlines()[-1])

    assert report == {"writable": ["/data", "/tmp"], "uid": 10001, "cap_eff": "0" * 16, "no_new_privs": "1"}  # noqa: S108

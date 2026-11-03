"""Pi operations targets of the Makefile (D99, D101, D176, D178; DEVOPS Makefile outline), offline.

`make -n` shows every docker command a target would send to pi-host; the ssh shim records the remote command,
which then runs against a fake install dir with the docker/curl/ss/df shims, so the real recipe text is exercised.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.common.state_delta import assert_state_delta, set_to, unchanged
from tests.deploy.conftest import (
    BASIC_AUTH_PASSWORD,
    CURRENT,
    IMAGE,
    NEW,
    OLDEST,
    PREVIOUS,
    REPO,
    FakePi,
    shim_env,
)

PI_TARGETS = ("pi-preflight", "status", "logs", "diag", "image-gc", "uninstall", "purge")
READ_ONLY = ("pi-preflight", "status", "logs", "diag")
DOCKER = re.compile(r"\bdocker\s+(?P<args>[^;|&)']*)")
MUTATING = re.compile(r"\b(rm|down|stop|kill|pull|up|run|create|restart|login|logout|prune)\b")
PURGE_WORD = "purge overland"


def dry_run(target: str) -> str:
    result = subprocess.run(["make", "-n", "-C", str(REPO), target], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout + (REPO / "deploy/scripts/pi-preflight.sh").read_text() * (target == "pi-preflight")


def docker_commands(text: str) -> list[str]:
    return [match.group("args").strip() for match in DOCKER.finditer(text)]


@pytest.mark.parametrize("target", PI_TARGETS)
def test_every_pi_target_stays_inside_project_overland(target: str) -> None:
    text = dry_run(target)
    commands = docker_commands(text)

    assert "ssh -o BatchMode=yes deploy@pi.example" in text
    assert commands, f"make {target} sends no docker command"
    assert "prune" not in text and "system" not in " ".join(commands) and "daemon.json" not in text  # D99
    for command in commands:
        verb = command.split()[0]
        if verb == "compose":  # `compose ls` only lists the projects (pi-preflight)
            assert command.startswith(("compose -p overland ", "compose ls ")), f"make {target}: docker {command}"
        elif verb == "image":
            assert command.startswith("image rm") or IMAGE in command, f"make {target}: docker {command}"
        elif verb == "volume":
            assert "overland_*)" in text, f"make {target}: docker {command} outside overland_* volumes"
        else:
            assert verb in ("stats", "ps"), f"make {target}: docker {command}"
        if target in READ_ONLY:
            assert not MUTATING.search(command), f"make {target} is read-only but runs docker {command}"


def run_make(target: str, shim_home: Path, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "-s", "-C", str(REPO), target, "PI_DIR=overland-planner"],
        input=stdin,
        env=shim_env(shim_home),
        capture_output=True,
        text=True,
        timeout=60,
    )


def remote(pi: FakePi, target: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    """Run `make target` on the Mac, then the command its ssh sent, in the fake Pi home (`cd overland-planner`)."""
    made = run_make(target, pi.shim_home, stdin)
    assert made.returncode == 0, made.stderr
    ssh = pi.calls("ssh")
    assert len(ssh) == 1, ssh
    return subprocess.run(
        ["bash", "-c", ssh[0]["argv"][-1]],
        cwd=pi.root,
        env=shim_env(pi.shim_home),
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture
def pi_home(tmp_path: Path) -> FakePi:
    return FakePi(tmp_path / "pi")


def image_rm_refs(pi: FakePi) -> list[str]:
    return [call["argv"][-1] for call in pi.calls("docker") if call["argv"][:2] == ["image", "rm"]]


def test_image_gc_keeps_the_three_release_digests(pi_home: FakePi) -> None:
    listed = [f"{IMAGE}@{release.digest}" for release in (OLDEST, PREVIOUS, CURRENT, NEW)]
    stale = f"{IMAGE}@sha256:{'9' * 64}"
    pi_home.rule("docker", "image ls", stdout="\n".join([*listed, stale, f"{IMAGE}@<none>"]) + "\n")

    result = remote(pi_home, "image-gc")

    assert result.returncode == 0, result.stderr
    assert sorted(image_rm_refs(pi_home)) == sorted([NEW.image, stale])  # release.env, .prev, .prev2 stay


@given(
    answer=st.text(
        alphabet=st.characters(blacklist_characters="\n\r", blacklist_categories=["Cs"]), max_size=20
    ).filter(lambda a: a != PURGE_WORD)
)
@settings(max_examples=15, deadline=None)
def test_purge_aborts_without_any_pi_call_unless_the_exact_word_is_typed(answer: str, tmp_path_factory: Any) -> None:
    shim_home = tmp_path_factory.mktemp("shim")
    before = {"pi_calls": [], "exit_code": 0, "nothing_removed": False}

    result = run_make("purge", shim_home, stdin=answer + "\n")

    calls_log = shim_home / "calls.jsonl"
    after = {
        "pi_calls": calls_log.read_text().splitlines() if calls_log.exists() else [],
        "exit_code": result.returncode,
        "nothing_removed": "aborted, nothing removed" in result.stderr,
    }
    assert_state_delta(
        before,
        after,
        universe={"pi_calls", "exit_code", "nothing_removed"},
        expected={"exit_code": set_to(2), "nothing_removed": set_to(True), "pi_calls": unchanged()},
        strict=True,
    )


def test_purge_with_the_word_removes_only_overland_volumes_and_planner_images(pi_home: FakePi) -> None:
    pi_home.rule("docker", "volume ls", stdout="overland_planner-data\nimmich_pgdata\noverland_valhalla-tiles\n")
    pi_home.rule("docker", "image ls", stdout=f"{CURRENT.image}\n{IMAGE}@<none>\n")

    result = remote(pi_home, "purge", stdin=PURGE_WORD + "\n")

    assert result.returncode == 0, result.stderr
    removed_volumes = [c["argv"][-1] for c in pi_home.calls("docker") if c["argv"][:2] == ["volume", "rm"]]
    assert removed_volumes == ["overland_planner-data", "overland_valhalla-tiles"]
    assert image_rm_refs(pi_home) == [CURRENT.image]
    downs = [c["argv"] for c in pi_home.calls("docker") if "down" in c["argv"]]
    assert len(downs) == 1 and downs[0][:3] == ["compose", "-p", "overland"] and "-v" not in downs[0]


def preflight(pi: FakePi, tmp: Path) -> subprocess.CompletedProcess[str]:
    meminfo = tmp / "meminfo"
    meminfo.write_text("MemTotal:  8000000 kB\nMemAvailable:  6000000 kB\n")
    script = (REPO / "deploy/scripts/pi-preflight.sh").read_text()
    return subprocess.run(
        ["bash", "-s", "--", "overland-planner"],
        input=script,
        env=shim_env(pi.shim_home, HOME=str(pi.root), MEMINFO=str(meminfo)),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_pi_preflight_reads_only_and_never_prints_the_password(pi_home: FakePi, tmp_path: Path) -> None:
    (pi_home.root / ".docker").mkdir()
    (pi_home.root / ".docker/config.json").write_text('{"auths": {"ghcr.io": {"auth": "c2VjcmV0"}}}')

    result = preflight(pi_home, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PLANNER_BIND=192.168.1.10" in result.stdout and "all checks passed" in result.stdout
    assert "WARN  registry access: per-deploy login (D196)" in result.stdout  # a stored ghcr.io login is unexpected
    assert BASIC_AUTH_PASSWORD not in result.stdout + result.stderr and "c2VjcmV0" not in result.stdout
    docker_verbs = [shlex.join(call["argv"][:2]) for call in pi_home.calls("docker")]
    assert set(docker_verbs) <= {"ps --filter", "compose ls"}


def test_pi_preflight_fails_without_planner_bind_not_without_stored_login(pi_home: FakePi, tmp_path: Path) -> None:
    env_file = pi_home.dir / ".env"
    env_file.write_text(
        "".join(line + "\n" for line in env_file.read_text().splitlines() if "PLANNER_BIND" not in line)
    )

    result = preflight(pi_home, tmp_path)

    assert result.returncode == 1
    assert "FAIL  .env has no PLANNER_BIND" in result.stdout and "1 check(s) failed" in result.stdout
    assert "ok    registry access: per-deploy login (D196)" in result.stdout

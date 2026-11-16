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
    BASIC_AUTH_USER,
    CURRENT,
    IMAGE,
    NEW,
    OLDEST,
    PI_BIND,
    PREVIOUS,
    REPO,
    FakePi,
    routing_profile_on,
    shim_env,
)

PI_TARGETS = ("pi-preflight", "status", "logs", "diag", "image-gc", "uninstall", "purge")
READ_ONLY = ("pi-preflight", "status", "logs", "diag")
DOCKER = re.compile(r"\bdocker\s+(?P<args>[^;|&)']*)")
MUTATING = re.compile(r"\b(rm|down|stop|kill|pull|up|run|create|restart|login|logout|prune)\b")
PURGE_WORD = "purge overland"
DEPLOY_USER = "deploy@pi.example"  # a placeholder: the real host lives in the untracked deploy/pi.env
NO_PI_ENV = "PI_ENV_FILE=/nonexistent/pi.env"


def dry_run(target: str) -> str:
    result = subprocess.run(
        ["make", "-n", "-C", str(REPO), target, f"PI_HOST={DEPLOY_USER}", NO_PI_ENV],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout + (REPO / "deploy/scripts/pi-preflight.sh").read_text() * (target == "pi-preflight")


def docker_commands(text: str) -> list[str]:
    return [match.group("args").strip() for match in DOCKER.finditer(text)]


@pytest.mark.parametrize("target", PI_TARGETS)
def test_every_pi_target_stays_inside_project_overland(target: str) -> None:
    text = dry_run(target)
    commands = docker_commands(text)

    assert f"ssh -o BatchMode=yes {DEPLOY_USER}" in text
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
        ["make", "-s", "-C", str(REPO), target, f"PI_HOST={DEPLOY_USER}", NO_PI_ENV, "PI_DIR=overland-planner"],
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


def test_diag_reads_the_diagnostics_with_the_env_credentials_and_never_prints_them(pi_home: FakePi) -> None:
    diagnostics = '{"version":"0123456789ab","k5":{"stage_p95_s":{"solve":41.0}}}'
    pi_home.rule("curl", "/api/diagnostics", stdout=diagnostics)

    result = remote(pi_home, "diag")

    assert result.returncode == 0, result.stderr
    assert diagnostics in result.stdout and '{"status":"ok"}' in result.stdout
    (call,) = [call for call in pi_home.calls("curl") if call["argv"][-1].endswith("/api/diagnostics")]
    assert call["argv"][-1] == f"http://{PI_BIND}:8080/api/diagnostics"
    assert "-K" in call["argv"] and f"{BASIC_AUTH_USER}:" in call["stdin"]  # the .env credentials, on stdin only
    shown = result.stdout + result.stderr + " ".join(call["argv"]) + " ".join(c["argv"][-1] for c in pi_home.calls())
    assert BASIC_AUTH_PASSWORD not in shown and "sh4red" not in shown


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
    assert f"PLANNER_BIND={PI_BIND}" in result.stdout and "all checks passed" in result.stdout
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


PERF_SCRIPT = REPO / "deploy/scripts/perf-pi.sh"


@pytest.mark.parametrize(
    ("variables", "expected"),
    [
        ((), ("N=10", "ITEMS=60", "POINTS= ")),
        (("N=30", "ITEMS=70"), ("N=30", "ITEMS=70")),
        (("POINTS=20000",), ("POINTS=20000",)),
    ],
)
def test_perf_pi_hands_its_mode_to_the_mac_side_script(variables: tuple[str, ...], expected: tuple[str, ...]) -> None:
    # bypass: a Makefile recipe is wiring; one dry run per mode shows the variables reach the script.
    result = subprocess.run(
        ["make", "-n", "-C", str(REPO), "perf-pi", f"PI_HOST={DEPLOY_USER}", NO_PI_ENV, *variables],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "bash deploy/scripts/perf-pi.sh" in result.stdout and f"PI_HOST={DEPLOY_USER}" in result.stdout
    assert all(part in result.stdout + " " for part in expected), result.stdout


def test_perf_pi_help_says_the_orchestrator_runs_it_and_its_docker_commands_name_only_planner_perf() -> None:
    help_line = next(line for line in (REPO / "Makefile").read_text().splitlines() if line.startswith("perf-pi:"))
    script = PERF_SCRIPT.read_text()
    commands = docker_commands(script)

    assert "orchestrator" in help_line and "start time" in help_line
    assert commands and all(command.startswith("compose -p overland --profile perf") for command in commands), commands
    for command in commands:
        if MUTATING.search(command):
            assert "planner-perf" in command, f"a mutating command must name planner-perf: docker {command}"
    assert "overland_planner-data" not in script and "prune" not in script


@pytest.mark.parametrize("target", [*PI_TARGETS, "deploy", "rollback", "perf-pi"])
def test_a_pi_target_without_a_host_stops_and_names_the_template(target: str) -> None:
    result = subprocess.run(
        ["make", "-n", "-C", str(REPO), target, NO_PI_ENV],
        capture_output=True,
        text=True,
        timeout=30,
        env=_no_host_env(),
    )

    assert result.returncode != 0
    assert "set PI_HOST (see deploy/pi.env.example)" in result.stderr + result.stdout


def _no_host_env() -> dict[str, str]:
    import os

    return {key: value for key, value in os.environ.items() if key != "PI_HOST"}


def test_the_untracked_pi_env_file_supplies_the_host_and_the_install_dir(tmp_path: Path) -> None:
    pi_env = tmp_path / "pi.env"
    pi_env.write_text("PI_HOST=owner@my-pi.example\nPI_DIR=apps/elsewhere\n")

    result = subprocess.run(
        ["make", "-n", "-C", str(REPO), "status", f"PI_ENV_FILE={pi_env}"],
        capture_output=True,
        text=True,
        timeout=30,
        env=_no_host_env(),
    )

    assert result.returncode == 0, result.stderr
    assert "ssh -o BatchMode=yes owner@my-pi.example" in result.stdout and "cd apps/elsewhere" in result.stdout


def test_the_template_has_placeholders_only_and_the_real_file_is_git_ignored() -> None:
    template = (REPO / "deploy/pi.env.example").read_text()
    ignored = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "deploy/pi.env"], capture_output=True, text=True, timeout=30
    )

    assert "PI_HOST=deploy@pi.example" in template and "PI_DIR=" in template
    assert ignored.returncode == 0, "deploy/pi.env must be git-ignored"


@pytest.mark.parametrize("script", ["make-deploy.sh", "perf-pi.sh"])
def test_a_mac_side_script_without_a_host_stops_and_names_the_template(script: str) -> None:
    env = {**_no_host_env(), "PI_ENV_FILE": "/nonexistent/pi.env"}

    result = subprocess.run(
        ["bash", str(REPO / "deploy/scripts" / script)], capture_output=True, text=True, timeout=30, env=env, cwd=REPO
    )

    assert result.returncode != 0
    assert "set PI_HOST (see deploy/pi.env.example)" in result.stderr


ROUTING_TARGETS = ("status", "logs", "diag", "uninstall")


def compose_argvs(pi: FakePi) -> list[list[str]]:
    return [c["argv"] for c in pi.calls("docker") if c["argv"][:1] == ["compose"]]


@pytest.mark.parametrize("target", ROUTING_TARGETS)
def test_pi_targets_turn_the_routing_profile_on_exactly_when_routing_env_exists(target: str, tmp_path: Path) -> None:
    without, with_routing = FakePi(tmp_path / "without"), FakePi(tmp_path / "with")
    (with_routing.dir / "routing.env").write_text("VALHALLA_TILESET=2026-10\n")

    assert remote(without, target).returncode == 0
    assert remote(with_routing, target).returncode == 0

    off, on = compose_argvs(without), compose_argvs(with_routing)
    assert off and all("--profile" not in argv and "routing.env" not in argv for argv in off)
    assert on and all(routing_profile_on(argv) for argv in on)


def test_purge_says_the_map_data_goes_too_and_removes_the_valhalla_volume(pi_home: FakePi) -> None:
    pi_home.rule("docker", "volume ls", stdout="overland_planner-data\noverland_valhalla-data\n")

    out = subprocess.run(
        ["make", "-n", "-C", str(REPO), "purge", f"PI_HOST={DEPLOY_USER}", NO_PI_ENV], capture_output=True, text=True
    ).stdout
    result = remote(pi_home, "purge", stdin=PURGE_WORD + "\n")

    assert "map data (about 4.9 GB, rebuilt only by make tiles-seed or make tiles-refresh)" in out
    assert "overland_valhalla-data" in [
        c["argv"][-1] for c in pi_home.calls("docker") if c["argv"][:2] == ["volume", "rm"]
    ]
    assert result.returncode == 0, result.stderr

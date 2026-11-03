"""Step 02-06: rollback with two release pointers (D90, D91, D165, D166, D176, D195), offline.

The real deploy/scripts/rollback.sh and the real `make rollback` run under /bin/bash with docker, curl, flock, gh,
ssh and rsync replaced by the shims in tests/deploy/shims. The fake Pi serves CURRENT, with PREVIOUS in
release.env.prev and OLDEST in release.env.prev2. Assertions are on observable effects only: external calls and
their order, the files the script leaves behind, exit codes and releases.log lines. The Pi rollback drill
(A -> B -> C -> rollback -> B -> rollback STEPS=2 -> A) is gated to the user.
"""

from __future__ import annotations

import fcntl
from typing import Any

import pytest

from tests.deploy.conftest import (
    CURRENT,
    IMAGE,
    OLDEST,
    PI_BIND,
    PREVIOUS,
    FakePi,
    MacCheckout,
    Release,
    release_env_text,
)

LOOPBACK = "127.0.0.1"
D176_FIELDS = ["ts", "action", "digest", "git_sha", "commit_ts", "alembic_head", "result", "reason"]
KEPT_LINES = "# pinned by Marco: keep\nPLANNER_NOTE=hand-written\nCOMPOSE_PROFILES=\n"
TARGETS = {"1": PREVIOUS, "2": OLDEST}


def compose_ups(pi: FakePi) -> list[dict[str, Any]]:
    return [c for c in pi.calls("docker") if c["argv"][:1] == ["compose"] and "up" in c["argv"]]


def published_images(pi: FakePi) -> list[str | None]:
    return [c["planner_image"] for c in compose_ups(pi) if c["bind_env"] is None]


def index_of(calls: list[dict[str, Any]], predicate: Any) -> int:
    return next(i for i, call in enumerate(calls) if predicate(call))


def is_curl(url_part: str) -> Any:
    return lambda call: call["tool"] == "curl" and url_part in call["argv"][-1]


def snapshot_runs(pi: FakePi, mode: str) -> list[dict[str, Any]]:
    return [c for c in pi.calls("docker") if c["argv"][:1] == ["run"] and mode in " ".join(c["argv"])]


def downgrades(pi: FakePi) -> list[dict[str, Any]]:
    return [c for c in pi.calls("docker") if "alembic" in c["argv"] and "downgrade" in c["argv"]]


def history(pi: FakePi) -> None:
    """releases.log and predeploy snapshots as two deploys (PREVIOUS, then CURRENT) left them."""
    snapshots = pi.dir / "snapshots"
    snapshots.mkdir()
    for name in ("predeploy-20261101T090500Z.tgz", "predeploy-20261102T090500Z.tgz", "predeploy-20261103T080000Z.tgz"):
        (snapshots / name).write_text("snapshot\n")
    with (pi.dir / "releases.log").open("a") as log:
        for ts, release, result in (
            ("2026-11-01T09:10:00Z", PREVIOUS, "ok"),
            ("2026-11-02T09:10:00Z", CURRENT, "ok"),
            ("2026-11-03T08:01:00Z", CURRENT, "unchanged"),  # the 20261103 snapshot belongs to a later deploy attempt
        ):
            log.write(
                f'{{"ts":"{ts}","action":"deploy","digest":"{release.digest}","git_sha":"{release.git_sha}",'
                f'"commit_ts":"{release.commit_ts}","alembic_head":"{release.alembic_head}","result":"{result}",'
                '"reason":""}\n'
            )


def assert_serving(pi: FakePi, release: Release) -> None:
    assert (pi.dir / "release.env").read_text() == release_env_text(release, extra=KEPT_LINES)
    assert published_images(pi)[-1] == release.image


# ---- rollback.sh on the Pi --------------------------------------------------------------------------------------


@pytest.mark.parametrize("steps", TARGETS.keys())
def test_rollback_steps_one_and_two(pi: FakePi, steps: str) -> None:
    result = pi.rollback(steps)

    assert result.returncode == 0, result.stderr
    assert_serving(pi, TARGETS[steps])
    assert (pi.dir / "release.env.failed").read_text() == pi.originals["release.env"]
    assert (pi.dir / "release.env.prev").read_text() == pi.originals["release.env.prev"]
    assert (pi.dir / "release.env.prev2").read_text() == pi.originals["release.env.prev2"]


def test_repeated_rollback_does_not_flip_flop(pi: FakePi) -> None:
    assert pi.rollback("1").returncode == 0
    ups_after_first = len(compose_ups(pi))

    second = pi.rollback("1")

    assert second.returncode == 0, second.stderr
    assert len(compose_ups(pi)) == ups_after_first
    assert_serving(pi, PREVIOUS)
    assert (pi.dir / "release.env.failed").read_text() == pi.originals["release.env"]
    assert pi.releases_log()[-1]["result"] == "unchanged"

    third = pi.rollback("2")

    assert third.returncode == 0, third.stderr
    assert_serving(pi, OLDEST)
    assert CURRENT.image not in published_images(pi)
    assert f"PLANNER_IMAGE={PREVIOUS.image}\n" in (pi.dir / "release.env.failed").read_text()


SCHEMA = {
    "newer schema": (CURRENT, PREVIOUS, True),
    "same schema": (PREVIOUS, OLDEST, False),
}


@pytest.mark.parametrize("case", SCHEMA.values(), ids=SCHEMA.keys())
def test_schema_downgrade_path_snapshots_first(pi: FakePi, case: tuple[Release, Release, bool]) -> None:
    current, target, schema_differs = case
    (pi.dir / "release.env").write_text(release_env_text(current, extra=KEPT_LINES))
    (pi.dir / "release.env.prev").write_text(release_env_text(target))

    result = pi.rollback()

    assert result.returncode == 0, result.stderr
    assert_serving(pi, target)
    if not schema_differs:
        assert downgrades(pi) == [] and snapshot_runs(pi, "czf") == []
        return
    calls = pi.calls()
    stop = index_of(calls, lambda c: c["tool"] == "docker" and "stop" in c["argv"])
    snapshot = calls.index(snapshot_runs(pi, "czf")[0])
    downgrade = calls.index(downgrades(pi)[0])
    switch = index_of(calls, lambda c: c in compose_ups(pi))
    assert stop < snapshot < downgrade < switch
    assert downgrades(pi)[0]["argv"][-3:] == ["alembic", "downgrade", target.alembic_head]
    assert downgrades(pi)[0]["planner_image"] == current.image
    assert "--rm" in downgrades(pi)[0]["argv"]
    assert "lost" in result.stderr  # D91: the user sees that newer-schema-only data can be lost
    assert snapshot_runs(pi, "xzf") == []


FAILED_DOWNGRADE = {
    "rollback one step": ("1", "predeploy-20261102T090500Z.tgz", "2026-11-02 09:05:00 UTC"),
    "rollback two steps": ("2", "predeploy-20261101T090500Z.tgz", "2026-11-01 09:05:00 UTC"),
}


@pytest.mark.parametrize("case", FAILED_DOWNGRADE.values(), ids=FAILED_DOWNGRADE.keys())
def test_failed_downgrade_restores_predeploy_snapshot(pi: FakePi, case: tuple[str, str, str]) -> None:
    steps, snapshot, taken = case
    history(pi)
    pi.rule("docker", "alembic", "downgrade", exit=1, stderr="alembic: downgrade failed\n")

    result = pi.rollback(steps)

    assert result.returncode == 0, result.stderr
    restored = snapshot_runs(pi, "xzf")
    assert [c["argv"][-1] for c in restored] == [snapshot]
    assert taken in result.stderr
    calls = pi.calls()
    assert calls.index(downgrades(pi)[0]) < calls.index(restored[0]) < index_of(calls, lambda c: c in compose_ups(pi))
    assert_serving(pi, TARGETS[steps])
    line = pi.releases_log()[-1]
    assert (line["action"], line["result"]) == ("rollback", "ok")
    assert snapshot in line["reason"] and "downgrade failed" in line["reason"]


def test_failed_downgrade_without_predeploy_snapshot_keeps_current_release(pi: FakePi) -> None:
    pi.rule("docker", "alembic", "downgrade", exit=1)

    result = pi.rollback()

    assert result.returncode != 0
    fresh = snapshot_runs(pi, "czf")[0]
    fresh_name = next(a for a in fresh["argv"] if a.startswith("/backup/")).removeprefix("/backup/")
    assert [c["argv"][-1] for c in snapshot_runs(pi, "xzf")] == [fresh_name]
    assert pi.pointers() == pi.originals
    assert published_images(pi) == [CURRENT.image]
    assert pi.releases_log()[-1]["result"] == "failed"


OUTCOMES = {
    "rolled back": ("1", None, ("ok", "")),
    "already on prev": ("1", "already", ("unchanged", "")),
    "image no longer on the Pi": (
        "1",
        ("docker", ("image", "inspect", PREVIOUS.digest), {"exit": 1, "stderr": "No such image\n"}),
        ("failed", "not on the Pi"),
    ),
    "loopback smoke fails": (
        "1",
        ("curl", (f"{LOOPBACK}:8080/healthz",), {"exit": 22}),
        ("failed", "loopback smoke"),
    ),
    "unknown STEPS": ("3", None, ("failed", "STEPS")),
}


@pytest.mark.parametrize("outcome", OUTCOMES.values(), ids=OUTCOMES.keys())
def test_rollback_appends_one_releases_log_line(pi: FakePi, outcome: tuple[Any, ...]) -> None:
    steps, setup, (result_value, reason) = outcome
    if setup == "already":
        (pi.dir / "release.env").write_text(pi.originals["release.env.prev"])
    elif setup is not None:
        pi.rule(setup[0], *setup[1], **setup[2])
    before = pi.releases_log()

    result = pi.rollback(steps)

    assert (result.returncode == 0) == (result_value in ("ok", "unchanged"))
    log = pi.releases_log()
    assert log[: len(before)] == before and len(log) == len(before) + 1
    line = log[-1]
    assert list(line) == D176_FIELDS
    assert (line["action"], line["result"]) == ("rollback", result_value)
    assert reason in line["reason"] and (reason or line["reason"] == "")
    if steps == "1":
        assert (line["digest"], line["git_sha"]) == (PREVIOUS.digest, PREVIOUS.git_sha)
    if result_value == "failed" and steps == "1" and setup != "already":
        assert reason in result.stderr
    if setup is not None and setup != "already" and setup[0] == "docker":
        assert compose_ups(pi) == [] and pi.pointers() == pi.originals


def test_concurrent_rollback_aborts_on_lock(pi: FakePi) -> None:
    with (pi.dir / ".deploy.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = pi.rollback()

    assert result.returncode != 0
    assert pi.calls("docker") == [] and pi.pointers() == pi.originals
    assert (pi.releases_log()[-1]["action"], pi.releases_log()[-1]["result"]) == ("rollback", "aborted")


@pytest.mark.parametrize("current", [CURRENT, PREVIOUS], ids=["newer schema", "same schema"])
def test_rollback_never_changes_routing_env(pi: FakePi, current: Release) -> None:
    routing = "VALHALLA_TILESET=2026-10\nPLANNER_IMAGE=must-not-be-read-from-here\n"
    (pi.dir / "routing.env").write_text(routing)
    (pi.dir / "release.env.prev").write_text(release_env_text(OLDEST if current == PREVIOUS else PREVIOUS))
    (pi.dir / "release.env").write_text(release_env_text(current, extra=KEPT_LINES))

    assert pi.rollback().returncode == 0

    assert (pi.dir / "routing.env").read_text() == routing
    assert not list(pi.dir.glob("routing.env?*"))
    compose = [c for c in pi.calls("docker") if c["argv"][:1] == ["compose"]]
    assert compose and all("routing.env" in c["argv"] for c in compose)


def test_rollback_skips_provenance_check(pi: FakePi) -> None:
    assert pi.rollback("2").returncode == 0

    for call in pi.calls("docker"):
        assert call["argv"][0] not in ("pull", "manifest", "login")
    assert pi.calls("gh") == []


def test_make_rollback_runs_rollback_sh_without_provenance(mac: MacCheckout) -> None:
    result = mac.make_rollback("STEPS=2")

    assert result.returncode == 0, result.stdout + result.stderr
    steps = [(c["tool"], " ".join(c["argv"])) for c in mac.calls()]
    assert [tool for tool, _ in steps] == ["ssh", "rsync"]
    assert "apps/overland-planner" in steps[0][1] and steps[0][1].endswith("bash scripts/rollback.sh 2")
    assert "releases.log" in steps[1][1] and steps[1][1].endswith(".data/ops/releases.log")


def test_rollback_publishes_only_after_loopback_smoke(pi: FakePi) -> None:
    result = pi.rollback()

    assert result.returncode == 0, result.stderr
    calls = pi.calls()
    loopback_up = index_of(calls, lambda c: c in compose_ups(pi) and c["bind_env"] == LOOPBACK)
    healthz = index_of(calls, is_curl(f"http://{LOOPBACK}:8080/healthz"))
    api_health = index_of(calls, is_curl(f"http://{LOOPBACK}:8080/api/health"))
    app_started = index_of(calls, lambda c: c["tool"] == "docker" and "logs" in c["argv"])
    publish = index_of(calls, lambda c: c in compose_ups(pi) and c["bind_env"] is None)
    lan_smoke = index_of(calls, is_curl(f"http://{PI_BIND}:8080/healthz"))
    assert loopback_up < healthz < api_health < app_started < publish < lan_smoke
    assert [c["planner_image"] for c in compose_ups(pi)] == [PREVIOUS.image, PREVIOUS.image]


SCOPE_SCENARIOS = {
    "same schema": None,
    "newer schema": "newer",
    "failed downgrade": ("docker", ("alembic", "downgrade"), {"exit": 1}),
}


@pytest.mark.parametrize("scenario", SCOPE_SCENARIOS.values(), ids=SCOPE_SCENARIOS.keys())
def test_rollback_stays_inside_the_overland_scope(pi: FakePi, scenario: Any) -> None:
    """D99 coexistence: only project `overland`, volume overland_planner-data, our image and files under its dir."""
    history(pi)
    if scenario is None:
        (pi.dir / "release.env").write_text(release_env_text(PREVIOUS, extra=KEPT_LINES))
        (pi.dir / "release.env.prev").write_text(release_env_text(OLDEST))
    elif scenario != "newer":
        pi.rule(scenario[0], *scenario[1], **scenario[2])

    pi.rollback()

    docker = pi.calls("docker")
    assert docker
    for call in docker:
        argv, joined = call["argv"], " ".join(call["argv"])
        assert "prune" not in argv and "rm" not in argv[:2] and "down" not in argv and "daemon.json" not in joined
        assert "-v" not in argv[:4] and "--volumes" not in argv
        assert call["cwd"] == str(pi.dir)
        if argv[0] == "compose":
            assert argv[1:3] == ["-p", "overland"]
            if "run" in argv:
                assert argv[argv.index("run") :][:3] == ["run", "--rm", "planner"]
        elif argv[0] == "image":
            assert argv[:2] == ["image", "inspect"] and argv[-1].startswith(f"{IMAGE}@sha256:")
        elif argv[0] == "run":
            volumes = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-v"]
            assert volumes[0].startswith("overland_planner-data:/data")
            assert volumes[1].startswith(f"{pi.dir}/snapshots:/backup")
            assert "alpine:3.22@sha256:" in joined and "--network" in argv
        else:
            assert argv[:3] == ["volume", "inspect", "overland_planner-data"]
    assert {path.name for path in pi.root.iterdir()} == {"overland-planner", "shim"}

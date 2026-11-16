"""Step 02-05: loopback-first deploy with automatic rollback (D89, D91, D165, D176, D195), offline.

The real deploy/scripts/deploy.sh and the real `make deploy` run under /bin/bash (3.2 on macOS, 5 on the Pi) with
docker, curl, df, flock, gh, ssh and rsync replaced by the shims in tests/deploy/shims. Assertions are on observable
effects only: the order of external calls, the files the scripts leave behind, exit codes and releases.log lines.
The Pi scenario "Marco brings the planner up on his Pi with one command" is gated to the user (never run here).
"""

from __future__ import annotations

import fcntl
from typing import Any

import pytest

from tests.deploy.conftest import (
    BASIC_AUTH_PASSWORD,
    BASIC_AUTH_USER,
    CURRENT,
    GH_TOKEN,
    IMAGE,
    NEW,
    OLDEST,
    PI_BIND,
    SOURCE,
    FakePi,
    MacCheckout,
    release_env_text,
    routing_profile_on,
)

LOOPBACK = "127.0.0.1"
D176_FIELDS = ["ts", "action", "digest", "git_sha", "commit_ts", "alembic_head", "result", "reason"]


def compose_ups(pi: FakePi) -> list[dict[str, Any]]:
    return [c for c in pi.calls("docker") if c["argv"][:1] == ["compose"] and "up" in c["argv"]]


def published(call: dict[str, Any]) -> bool:
    """A compose `up` that publishes on the .env PLANNER_BIND (no loopback override in the environment)."""
    return call["bind_env"] is None


def index_of(calls: list[dict[str, Any]], predicate: Any) -> int:
    return next(i for i, call in enumerate(calls) if predicate(call))


def is_curl(url_part: str) -> Any:
    return lambda call: call["tool"] == "curl" and url_part in call["argv"][-1]


def snapshot_runs(pi: FakePi, mode: str) -> list[dict[str, Any]]:
    return [c for c in pi.calls("docker") if c["argv"][:1] == ["run"] and mode in " ".join(c["argv"])]


# ---- deploy.sh on the Pi ----------------------------------------------------------------------------------------


def test_publishes_only_after_loopback_smoke(pi: FakePi) -> None:
    result = pi.deploy(NEW.digest)

    assert result.returncode == 0, result.stderr
    calls = pi.calls()
    loopback_up = index_of(calls, lambda c: c in compose_ups(pi) and c["bind_env"] == LOOPBACK)
    healthz = index_of(calls, is_curl(f"http://{LOOPBACK}:8080/healthz"))
    api_health = index_of(calls, is_curl(f"http://{LOOPBACK}:8080/api/health"))
    app_started = index_of(calls, lambda c: c["tool"] == "docker" and "logs" in c["argv"])
    publish = index_of(calls, lambda c: c in compose_ups(pi) and published(c))
    lan_smoke = index_of(calls, is_curl(f"http://{PI_BIND}:8080/healthz"))
    assert loopback_up < healthz < api_health < app_started < publish < lan_smoke
    assert [published(c) for c in compose_ups(pi)] == [False, True]
    assert all(c["planner_image"] == NEW.image for c in compose_ups(pi))
    # /api/health is behind the household password: credentials go to curl on stdin, never on its command line.
    auth_call = calls[api_health]
    assert BASIC_AUTH_PASSWORD not in " ".join(auth_call["argv"])
    assert f"{BASIC_AUTH_USER}:" in auth_call["stdin"] and "family" in auth_call["stdin"]
    assert BASIC_AUTH_PASSWORD not in result.stdout + result.stderr


def test_deploy_rotates_pointers_preserving_other_lines(pi: FakePi) -> None:
    before = pi.pointers()

    assert pi.deploy(NEW.digest).returncode == 0

    after = pi.pointers()
    assert after["release.env.prev"] == before["release.env"]
    assert after["release.env.prev2"] == before["release.env.prev"]
    assert after["release.env"] == release_env_text(
        NEW, extra="# pinned by Marco: keep\nPLANNER_NOTE=hand-written\nCOMPOSE_PROFILES=\n"
    )


LOOPBACK_FAILURES = {
    "loopback start not healthy": ("docker", ("compose", "up"), {"bind_env": LOOPBACK, "exit": 1}, "loopback start"),
    "healthz unhealthy": ("curl", (f"{LOOPBACK}:8080/healthz",), {"exit": 22}, "/healthz"),
    "fatal component": (
        "curl",
        ("/api/health",),
        {"stdout": '{"status":"unhealthy","components":{"database":{"outcome": "fatal","reason":"x"}},"banners":[]}'},
        "fatal",
    ),
    "app_version mismatch": (
        "docker",
        ("compose", "logs"),
        {"stdout": '{"event": "app.started", "app_version": "' + CURRENT.git_sha + '"}\n'},
        "app_version",
    ),
}


@pytest.mark.parametrize("failure", LOOPBACK_FAILURES.values(), ids=LOOPBACK_FAILURES.keys())
def test_failure_before_publish_restores_snapshot_and_previous_release(pi: FakePi, failure: tuple[Any, ...]) -> None:
    tool, args_contain, answer, reason = failure
    pi.rule(tool, *args_contain, times=1, **answer)

    result = pi.deploy(NEW.digest)

    assert result.returncode != 0
    taken = snapshot_runs(pi, "czf")
    restored = snapshot_runs(pi, "xzf")
    assert len(taken) == 1 and len(restored) == 1
    snapshot = next(arg for arg in taken[0]["argv"] if arg.startswith("/backup/predeploy-")).removeprefix("/backup/")
    assert restored[0]["argv"][-1] == snapshot
    assert (pi.dir / "snapshots" / snapshot).is_file()
    assert pi.pointers() == pi.originals
    calls = pi.calls()
    assert calls.index(restored[0]) < index_of(
        calls, lambda c: c in compose_ups(pi) and c["planner_image"] == CURRENT.image
    )
    assert not [c for c in compose_ups(pi) if published(c) and c["planner_image"] == NEW.image]
    assert [c["planner_image"] for c in compose_ups(pi) if published(c)] == [CURRENT.image]
    line = pi.releases_log()[-1]
    assert (line["action"], line["result"], line["digest"]) == ("auto-rollback", "ok", NEW.digest)
    assert reason in line["reason"]


def test_failure_after_publish_rolls_back_digest_only(pi: FakePi) -> None:
    pi.rule("curl", f"{PI_BIND}:8080/healthz", times=1, exit=7)

    result = pi.deploy(NEW.digest)

    assert result.returncode != 0
    assert snapshot_runs(pi, "xzf") == []
    assert pi.pointers() == pi.originals
    assert [c["planner_image"] for c in compose_ups(pi) if published(c)] == [NEW.image, CURRENT.image]
    line = pi.releases_log()[-1]
    assert (line["action"], line["result"], line["digest"]) == ("auto-rollback", "ok", NEW.digest)
    assert "publish" in line["reason"]


OUTCOMES = {
    "deployed": (NEW.digest, None, ("deploy", "ok", "")),
    "unchanged": (CURRENT.digest, None, ("deploy", "unchanged", "")),
    "auto-rollback before publish": (
        NEW.digest,
        ("curl", (f"{LOOPBACK}:8080/healthz",), {"exit": 22, "times": 1}),
        ("auto-rollback", "ok", "loopback smoke"),
    ),
    "auto-rollback after publish": (
        NEW.digest,
        ("curl", (f"{PI_BIND}:8080/healthz",), {"exit": 7, "times": 1}),
        ("auto-rollback", "ok", "publish"),
    ),
    "refused at preflight": (
        NEW.digest,
        ("docker", ("manifest", "inspect"), {"stdout": '{"manifests":[{"platform":{"architecture":"amd64"}}]}'}),
        ("deploy", "failed", "linux/arm64"),
    ),
    "pull fails": (OLDEST.digest.replace("0", "9"), None, ("deploy", "failed", "pull")),
}


@pytest.mark.parametrize("outcome", OUTCOMES.values(), ids=OUTCOMES.keys())
def test_every_deploy_outcome_appends_one_releases_log_line(pi: FakePi, outcome: tuple[Any, ...]) -> None:
    digest, rule, (action, result, reason) = outcome
    if rule is not None:
        tool, args_contain, answer = rule
        pi.rule(tool, *args_contain, **answer)
    before = pi.releases_log()

    pi.deploy(digest)

    log = pi.releases_log()
    assert log[: len(before)] == before and len(log) == len(before) + 1
    line = log[-1]
    assert list(line) == D176_FIELDS
    assert (line["action"], line["result"], line["digest"]) == (action, result, digest)
    assert reason in line["reason"] and (reason or line["reason"] == "")
    release = {r.digest: r for r in (CURRENT, NEW)}.get(digest)
    if result != "failed":  # a refused deploy never read the image labels
        assert release is not None
        assert (line["git_sha"], line["commit_ts"], line["alembic_head"]) == (
            release.git_sha,
            release.commit_ts,
            release.alembic_head,
        )


def test_concurrent_deploy_aborts_on_lock(pi: FakePi) -> None:
    with (pi.dir / ".deploy.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = pi.deploy(NEW.digest)

    assert result.returncode != 0
    assert "deploy already running" in result.stderr
    assert pi.calls("docker") == []
    assert pi.pointers() == pi.originals
    assert (pi.releases_log()[-1]["result"], pi.releases_log()[-1]["reason"]) == ("aborted", "deploy already running")


def test_same_digest_is_unchanged(pi: FakePi) -> None:
    result = pi.deploy(CURRENT.digest)

    assert result.returncode == 0
    for call in pi.calls("docker"):
        assert call["argv"][0] not in ("pull", "run") and not {"up", "stop"} & set(call["argv"])
    assert pi.pointers() == pi.originals
    assert pi.releases_log()[-1]["result"] == "unchanged"


SCOPE_SCENARIOS = {
    "deployed": None,
    "rollback before publish": ("curl", (f"{LOOPBACK}:8080/healthz",), {"exit": 22, "times": 1}),
    "rollback after publish": ("curl", (f"{PI_BIND}:8080/healthz",), {"exit": 7, "times": 1}),
}


@pytest.mark.parametrize("rule", SCOPE_SCENARIOS.values(), ids=SCOPE_SCENARIOS.keys())
def test_deploy_stays_inside_the_overland_scope(pi: FakePi, rule: tuple[Any, ...] | None) -> None:
    """D99 coexistence: only project `overland`, volume overland_planner-data, our image and files under its dir."""
    if rule is not None:
        pi.rule(rule[0], *rule[1], **rule[2])

    pi.deploy(NEW.digest)

    docker = pi.calls("docker")
    assert docker
    for call in docker:
        argv, joined = call["argv"], " ".join(call["argv"])
        assert "prune" not in argv and "rm" not in argv[:2] and "down" not in argv and "daemon.json" not in joined
        assert call["cwd"] == str(pi.dir)
        if argv[0] == "compose":
            assert argv[1:3] == ["-p", "overland"]
        elif argv[0] in ("login", "logout"):  # D196: per-deploy login to our registry only
            assert argv in (["login", "ghcr.io", "-u", "MrMilgauss", "--password-stdin"], ["logout", "ghcr.io"])
        elif argv[0] in ("pull", "manifest", "image"):
            assert argv[-1].startswith(f"{IMAGE}@sha256:")
        elif argv[0] == "run":
            volumes = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-v"]
            assert volumes[0].startswith("overland_planner-data:/data")
            assert volumes[1].startswith(f"{pi.dir}/snapshots:/backup")
            assert "alpine:3.22@sha256:" in joined and "--network" in argv
        else:
            assert argv[:3] == ["volume", "inspect", "overland_planner-data"]
    assert {path.name for path in pi.root.iterdir()} == {"overland-planner", "shim"}


# ---- D196: per-deploy GHCR login, nothing stored on the Pi -------------------------------------------------------

REGISTRY_PATHS = {
    "deployed": (NEW.digest, None),
    "unchanged": (CURRENT.digest, None),
    "login refused": (NEW.digest, ("docker", ("login",), {"exit": 1, "stderr": "denied\n"})),
    "refused at preflight": (
        NEW.digest,
        ("docker", ("manifest", "inspect"), {"stdout": '{"manifests":[{"platform":{"architecture":"amd64"}}]}'}),
    ),
    "pull fails": (OLDEST.digest.replace("0", "9"), None),
    "auto-rollback before publish": (NEW.digest, ("curl", (f"{LOOPBACK}:8080/healthz",), {"exit": 22, "times": 1})),
    "auto-rollback after publish": (NEW.digest, ("curl", (f"{PI_BIND}:8080/healthz",), {"exit": 7, "times": 1})),
    "rollback fails too": (NEW.digest, ("curl", ("/healthz",), {"exit": 22})),
}


def registry_calls(pi: FakePi) -> list[dict[str, Any]]:
    return [c for c in pi.calls("docker") if c["argv"][0] in ("login", "logout", "pull", "manifest")]


@pytest.mark.parametrize("path", REGISTRY_PATHS.values(), ids=REGISTRY_PATHS.keys())
def test_registry_login_is_per_deploy_and_always_logged_out(pi: FakePi, path: tuple[Any, ...]) -> None:
    digest, rule = path
    if rule is not None:
        pi.rule(rule[0], *rule[1], **rule[2])

    result = pi.deploy(digest)

    verbs = [c["argv"][0] for c in registry_calls(pi)]
    assert verbs[0] == "login" and verbs[-1] == "logout" and verbs.count("login") == 1, verbs
    login = registry_calls(pi)[0]
    assert login["argv"][-1] == "--password-stdin" and login["stdin"] == f"{GH_TOKEN}\n"
    assert not (pi.shim_home / "docker-auth.json").exists()  # docker's login state is gone on every path
    assert all(c["argv"][0] != "login" for c in pi.calls("docker")[pi.calls("docker").index(login) + 1 :])
    if rule is None and digest == NEW.digest:
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path", REGISTRY_PATHS.values(), ids=REGISTRY_PATHS.keys())
def test_gh_token_never_leaks_on_the_pi(pi: FakePi, path: tuple[Any, ...]) -> None:
    digest, rule = path
    if rule is not None:
        pi.rule(rule[0], *rule[1], **rule[2])

    result = pi.deploy(digest)

    assert GH_TOKEN not in result.stdout + result.stderr
    assert all(GH_TOKEN not in " ".join(c["argv"]) for c in pi.calls())
    written = [f for f in pi.root.rglob("*") if f.is_file() and pi.shim_home not in f.parents]
    assert written and all(GH_TOKEN not in f.read_text(errors="replace") for f in written)


def test_deploy_without_a_token_on_stdin_refuses_before_any_registry_call(pi: FakePi) -> None:
    result = pi.deploy(NEW.digest, token="")

    assert result.returncode != 0
    assert registry_calls(pi) == []
    assert pi.pointers() == pi.originals
    line = pi.releases_log()[-1]
    assert (line["action"], line["result"]) == ("deploy", "failed") and "token" in line["reason"]


# ---- make deploy on the Mac -------------------------------------------------------------------------------------

GOOD_VCS = {"source": SOURCE + ".git", "revision": NEW.git_sha}


def deploy_calls(mac: MacCheckout) -> list[dict[str, Any]]:
    return [c for c in mac.calls() if c["tool"] == "rsync" or "deploy.sh" in " ".join(c["argv"])]


def test_make_deploy_ships_the_verified_digest_to_the_pi(mac: MacCheckout) -> None:
    digest = mac.registry.publish(dict.fromkeys(("linux/amd64", "linux/arm64"), GOOD_VCS))
    mac.green_run(NEW.git_sha, digest)

    result = mac.make_deploy()

    assert result.returncode == 0, result.stdout + result.stderr
    steps = [(c["tool"], " ".join(c["argv"])) for c in mac.calls() if c["tool"] in ("ssh", "rsync")]
    assert [tool for tool, _ in steps] == ["ssh", "rsync", "ssh", "rsync"]
    assert ".env" in steps[0][1] and "PLANNER_BIND" in steps[0][1]
    assert (
        "--exclude=.env" in steps[1][1]
        and "--delete" not in steps[1][1]
        and steps[1][1].endswith("apps/overland-planner/")
    )
    assert f"scripts/deploy.sh {digest}" in steps[2][1]
    assert "releases.log" in steps[3][1] and ".data/ops/releases.log" in steps[3][1]


def test_make_deploy_hands_the_gh_token_to_the_pi_only_on_ssh_stdin(mac: MacCheckout) -> None:
    digest = mac.registry.publish(dict.fromkeys(("linux/amd64", "linux/arm64"), GOOD_VCS))
    mac.green_run(NEW.git_sha, digest)

    result = mac.make_deploy()

    assert result.returncode == 0, result.stdout + result.stderr
    remote = [c for c in mac.calls("ssh") if "deploy.sh" in " ".join(c["argv"])]
    assert len(remote) == 1 and remote[0]["stdin"] == f"{GH_TOKEN}\n"
    assert all(GH_TOKEN not in " ".join(c["argv"]) for c in mac.calls())
    assert GH_TOKEN not in result.stdout + result.stderr
    files = [f for f in mac.dir.rglob("*") if f.is_file() and ".git" not in f.parts]
    assert all(GH_TOKEN not in f.read_text(errors="replace") for f in files)


GATES = {
    "no green ci.yml run for the SHA": ("SHA", lambda mac, digest: None, "no successful ci.yml run"),
    "green run without release.json": (
        "SHA",
        lambda mac, digest: mac.green_run(NEW.git_sha, digest, release_json=False),
        "release.json",
    ),
    "no green run with release.json at all (default SHA)": ("", lambda mac, digest: None, "release.json"),
    "dirty working tree": (
        "SHA",
        lambda mac, digest: (mac.green_run(NEW.git_sha, digest), (mac.dir / "Makefile").open("a").write("\n")),
        "not clean",
    ),
}


@pytest.mark.parametrize("gate", GATES.values(), ids=GATES.keys())
def test_make_deploy_refuses_without_green_run(mac: MacCheckout, gate: tuple[Any, ...]) -> None:
    sha_mode, script, message = gate
    digest = mac.registry.publish(dict.fromkeys(("linux/amd64", "linux/arm64"), GOOD_VCS))
    script(mac, digest)

    result = mac.make_deploy(*([f"SHA={NEW.git_sha}"] if sha_mode else []))

    assert result.returncode != 0
    assert message in result.stderr
    assert deploy_calls(mac) == []


PROVENANCE = {
    "arm64 has no provenance": ({"linux/amd64": GOOD_VCS, "linux/arm64": None}, False, "linux/arm64"),
    "amd64 built from another commit": (
        {"linux/amd64": {**GOOD_VCS, "revision": CURRENT.git_sha}, "linux/arm64": GOOD_VCS},
        False,
        "linux/amd64",
    ),
    "built from another repository": (
        {p: {**GOOD_VCS, "source": "https://github.com/evil/overland-planner"} for p in ("linux/amd64", "linux/arm64")},
        False,
        "evil",
    ),
    "gh token cannot read packages": (dict.fromkeys(("linux/amd64", "linux/arm64"), GOOD_VCS), True, "read:packages"),
}


@pytest.mark.parametrize("case", PROVENANCE.values(), ids=PROVENANCE.keys())
def test_make_deploy_refuses_on_missing_or_mismatched_provenance(mac: MacCheckout, case: tuple[Any, ...]) -> None:
    vcs_by_platform, refuse_token, message = case
    digest = mac.registry.publish(vcs_by_platform)
    mac.registry.refuse_token = refuse_token
    mac.green_run(NEW.git_sha, digest)

    result = mac.make_deploy(f"SHA={NEW.git_sha}")

    assert result.returncode != 0
    assert message in result.stderr
    assert deploy_calls(mac) == []
    assert all(c["argv"][:1] != ["rsync"] for c in mac.calls())


def test_make_deploy_refuses_without_pi_settings(mac: MacCheckout) -> None:
    digest = mac.registry.publish(dict.fromkeys(("linux/amd64", "linux/arm64"), GOOD_VCS))
    mac.green_run(NEW.git_sha, digest)
    mac.rule("ssh", ".env", "PLANNER_BIND", exit=1)

    result = mac.make_deploy(f"SHA={NEW.git_sha}")

    assert result.returncode != 0
    assert "PLANNER_BIND" in result.stderr and ".env.example" in result.stderr
    assert mac.calls("rsync") == [] and len(mac.calls("ssh")) == 1


# ---- the routing engine follows a planner deploy without ever failing it (D234, D239) ---------------------------


def test_with_routing_env_every_compose_call_turns_the_profile_on_and_valhalla_starts_after_the_publish(
    pi: FakePi,
) -> None:
    (pi.dir / "routing.env").write_text("VALHALLA_TILESET=2026-10\n")

    result = pi.deploy(NEW.digest)

    assert result.returncode == 0, result.stderr
    compose = [c for c in pi.calls("docker") if c["argv"][:1] == ["compose"]]
    assert compose and all(routing_profile_on(c["argv"]) for c in compose)
    (valhalla,) = pi.valhalla_ups()
    assert valhalla["argv"][-3:] == ["up", "-d", "valhalla"] and "--wait" not in valhalla["argv"]
    calls = pi.calls()
    publish = index_of(calls, lambda c: c in compose_ups(pi) and published(c))
    assert publish < calls.index(valhalla)
    assert pi.releases_log()[-1]["result"] == "ok"


def test_without_routing_env_deploy_makes_no_valhalla_call_and_no_profile_flag(pi: FakePi) -> None:
    assert pi.deploy(NEW.digest).returncode == 0

    assert pi.valhalla_ups() == []
    assert all("--profile" not in c["argv"] and "routing.env" not in c["argv"] for c in pi.calls("docker"))


def test_a_failing_valhalla_start_leaves_the_deploy_ok_and_says_so_in_one_line(pi: FakePi) -> None:
    (pi.dir / "routing.env").write_text("VALHALLA_TILESET=2026-10\n")
    pi.rule("docker", "compose", "valhalla", exit=1)

    result = pi.deploy(NEW.digest)

    assert result.returncode == 0, result.stderr
    assert [line for line in result.stderr.splitlines() if "valhalla" in line.lower()] == [
        "deploy: valhalla did not start (the planner is not affected)"
    ]
    assert (pi.releases_log()[-1]["action"], pi.releases_log()[-1]["result"]) == ("deploy", "ok")
    assert pi.pointers()["release.env"].startswith(f"PLANNER_IMAGE={NEW.image}")

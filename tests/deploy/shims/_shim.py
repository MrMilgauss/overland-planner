"""Shared engine of the fake external commands for the offline deploy tests (docker, curl, df, flock, gh, ssh, rsync,
ss).

Each shim appends one JSON record per invocation to `$SHIM_HOME/calls.jsonl` (tool, argv, cwd, PLANNER_BIND from the
environment, curl's stdin config, the PLANNER_IMAGE of the release.env compose would read) and then answers:

1. with the first scripted rule of `$SHIM_HOME/rules.json` that matches (tool + substrings of the joined argv), a
   rule with `times` stops matching after that many uses; or
2. with the behaviour of a healthy Pi / GitHub (defaults below).

`$SHIM_HOME/images.json` maps a digest to its OCI labels; `docker pull` of an unknown digest fails.
GHCR is private: `docker login ghcr.io --password-stdin` stores `$SHIM_HOME/docker-auth.json` (docker's transient
login state), `docker logout ghcr.io` removes it, and `docker pull` / `docker manifest inspect` fail without it.
The stdin of `docker login --password-stdin` and of an ssh running deploy.sh is recorded (the D196 token channel).
`flock -n <fd>` takes a real non-blocking flock(2) on the inherited descriptor, exactly like util-linux flock.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HOME = Path(os.environ["SHIM_HOME"])
HEALTHZ_OK = '{"status":"ok"}'
API_HEALTH_OK = '{"status":"ok","components":{"database":{"outcome":"ok","reason":null}},"banners":[]}'


def main(tool: str) -> None:
    argv = sys.argv[1:]
    record = _record(tool, argv)
    with (HOME / "calls.jsonl").open("a") as log:
        log.write(json.dumps(record) + "\n")
    rule = _matching_rule(tool, argv)
    if rule is not None:
        _answer(tool, argv, rule)
    _default(tool, argv, record)


def _record(tool: str, argv: list[str]) -> dict[str, Any]:
    stdin = sys.stdin.read() if _reads_stdin(tool, argv) else ""
    record: dict[str, Any] = {"tool": tool, "argv": argv, "cwd": os.getcwd(), "stdin": stdin}
    record["bind_env"] = os.environ.get("PLANNER_BIND")
    if tool == "docker" and argv[:1] == ["compose"]:
        record["planner_image"] = _release_value("PLANNER_IMAGE", argv)
    return record


def _reads_stdin(tool: str, argv: list[str]) -> bool:
    if tool == "curl":
        return "-K" in argv
    if tool == "docker":
        return argv[:1] == ["login"] and "--password-stdin" in argv
    return tool == "ssh" and "deploy.sh" in " ".join(argv)


def _release_value(key: str, argv: list[str]) -> str | None:
    files = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "--env-file" and "release" in argv[i + 1]]
    if not files or not Path(files[-1]).is_file():
        return None
    value = None
    for line in Path(files[-1]).read_text().splitlines():
        if line.startswith(key + "="):
            value = line.split("=", 1)[1]
    return value


def _matching_rule(tool: str, argv: list[str]) -> dict[str, Any] | None:
    rules_file = HOME / "rules.json"
    if not rules_file.is_file():
        return None
    rules = json.loads(rules_file.read_text())
    joined = " ".join(argv)
    for rule in rules:
        if rule["tool"] != tool or not all(part in joined for part in rule.get("args_contain", [])):
            continue
        if "bind_env" in rule and os.environ.get("PLANNER_BIND") != rule["bind_env"]:
            continue
        if "times" in rule:
            if rule["times"] <= 0:
                continue
            rule["times"] -= 1
            rules_file.write_text(json.dumps(rules))
        return rule
    return None


def _answer(tool: str, argv: list[str], rule: dict[str, Any]) -> None:
    if tool == "gh" and "release_json" in rule and argv[:2] == ["run", "download"]:
        target = Path(argv[argv.index("--dir") + 1])
        target.mkdir(parents=True, exist_ok=True)
        (target / "release.json").write_text(json.dumps(rule["release_json"]))
    sys.stdout.write(rule.get("stdout", ""))
    sys.stderr.write(rule.get("stderr", ""))
    sys.exit(rule.get("exit", 0))


def _default(tool: str, argv: list[str], record: dict[str, Any]) -> None:
    handler = {"docker": _docker, "curl": _curl, "df": _df, "flock": _flock}.get(tool)
    if handler is not None:
        handler(argv, record)
    sys.exit(0)


def _docker(argv: list[str], record: dict[str, Any]) -> None:
    images = json.loads((HOME / "images.json").read_text()) if (HOME / "images.json").is_file() else {}
    auth = HOME / "docker-auth.json"
    if argv[:1] == ["login"]:
        if not record["stdin"].strip():
            sys.stderr.write("Error: Cannot perform an interactive login from a non TTY device\n")
            sys.exit(1)
        auth.write_text(json.dumps({"auths": {argv[1]: {"user": argv[argv.index("-u") + 1]}}}))
        print("Login Succeeded")
    elif argv[:1] == ["logout"]:
        auth.unlink(missing_ok=True)
        print(f"Removing login credentials for {argv[1]}")
    elif (argv[:1] == ["pull"] or argv[:2] == ["manifest", "inspect"]) and not auth.is_file():
        sys.stderr.write("unauthorized: authentication required\n")
        sys.exit(1)
    elif argv[:1] == ["compose"] and "logs" in argv:
        version = _release_value("PLANNER_GIT_SHA", argv) or "dev"
        print(
            json.dumps({"ts": "2026-11-03T08:00:00Z", "level": "info", "event": "app.started", "app_version": version})
        )
    elif argv[:2] == ["manifest", "inspect"]:
        platforms = [{"platform": {"architecture": arch, "os": "linux"}} for arch in ("amd64", "arm64")]
        print(json.dumps({"manifests": platforms}, indent=3))
    elif argv[:1] == ["pull"]:
        if argv[-1].split("@")[-1] not in images:
            sys.stderr.write("manifest unknown\n")
            sys.exit(1)
    elif argv[:2] == ["image", "inspect"]:
        labels = images[argv[-1].split("@")[-1]]
        template = argv[argv.index("--format") + 1]
        print(re.sub(r'\{\{index \.Config\.Labels "([^"]+)"\}\}', lambda m: labels.get(m.group(1), ""), template))
    elif argv[:1] == ["run"] and "czf" in argv:
        mounts = dict(reversed(argv[i + 1].split(":")[:2]) for i, arg in enumerate(argv) if arg == "-v")
        archive = argv[argv.index("czf") + 1]
        host_dir = mounts[os.path.dirname(archive)]
        (Path(host_dir) / os.path.basename(archive)).write_text("snapshot of overland_planner-data\n")


def _curl(argv: list[str], record: dict[str, Any]) -> None:
    url = argv[-1]
    if url.endswith("/healthz"):
        print(HEALTHZ_OK)
    elif url.endswith("/api/health"):
        print(API_HEALTH_OK)


def _df(argv: list[str], record: dict[str, Any]) -> None:
    print("Filesystem 1024-blocks Used Available Capacity Mounted on")
    print("/dev/nvme0n1p2 245000000 20000000 220000000 9% /")


def _flock(argv: list[str], record: dict[str, Any]) -> None:
    descriptor = int(argv[-1])
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(1)

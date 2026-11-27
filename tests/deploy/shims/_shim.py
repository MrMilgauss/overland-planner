"""Shared engine of the fake external commands for the offline deploy tests (docker, curl, df, flock, gh, ssh, rsync,
ss, crontab, timeout).

Each shim appends one JSON record per invocation to `$SHIM_HOME/calls.jsonl` (tool, argv, cwd, PLANNER_BIND from the
environment, curl's stdin config, the PLANNER_IMAGE of the release.env compose would read) and then answers:

1. with the first scripted rule of `$SHIM_HOME/rules.json` that matches (tool + substrings of the joined argv), a
   rule with `times` stops matching after that many uses; or
2. with the behaviour of a healthy Pi / GitHub (defaults below).

`$SHIM_HOME/images.json` maps a digest to its OCI labels; `docker pull` of an unknown digest fails.
GHCR is private: `docker login ghcr.io --password-stdin` stores `$SHIM_HOME/docker-auth.json` (docker's transient
login state), `docker logout ghcr.io` removes it, and `docker pull` / `docker manifest inspect` fail without it.
`docker run ... sh -c SCRIPT LABEL ARG...` of the tile helper container (mounts at /seed, /vol, /target) really runs
SCRIPT with the local sh: the mount destinations are replaced by the host directories (a volume NAME by
`$SHIM_HOME/volumes/NAME`), so cp, find, test and the `sha256sum` shim act on real files; a scripted rule can still
answer a call by its LABEL (the `$0` of the script).
A rule may also carry: `kill_parent` (a signal name sent to the calling script before the answer: a dropped ssh
session), `mkdir` (a path made below the fake volume first: something that appears between two calls), `passthrough`
(after those side effects the call gets the default behaviour, not the rule's answer), `routing_tileset` (matches only
while routing.env of the current directory names that tileset), `sleep` (seconds to wait before answering).
`$SHIM_HOME/status_by_tileset.json` maps a tileset to the tileset_last_modified the valhalla /status answers while
routing.env names it. An `ssh ... -N -L` forward lives (sleeps) until it is killed, unless a rule makes it exit.
The stdin of `docker login --password-stdin` and of an ssh running deploy.sh is recorded (the D196 token channel).
`flock -n <fd>` takes a real non-blocking flock(2) on the inherited descriptor, exactly like util-linux flock.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HOME = Path(os.environ["SHIM_HOME"])
HEALTHZ_OK = '{"status":"ok"}'
VALHALLA_STATUS_OK = '{"version":"3.9.1","tileset_last_modified":1793560782,"available_actions":["status","route"]}'
BUILD_TIME = 1700000000  # modification time the scripted tile build gives valhalla_tiles.tar
HELPER_MOUNTS = ("/seed", "/vol", "/target")
MATCHED: dict[str, Any] | None = (
    None  # the scripted rule of this call (a `passthrough` rule can still shape the default)
)
API_HEALTH_OK = '{"status":"ok","components":{"database":{"outcome":"ok","reason":null}},"banners":[]}'


def main(tool: str) -> None:
    argv = sys.argv[1:]
    record = _record(tool, argv)
    with (HOME / "calls.jsonl").open("a") as log:
        log.write(json.dumps(record) + "\n")
    rule = _matching_rule(tool, argv)
    global MATCHED
    MATCHED = rule
    if rule is not None:
        _side_effects(rule)
        if not rule.get("passthrough"):
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
    if tool == "crontab":
        return False  # the handler reads it itself: a recording read would leave the handler nothing
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
        if "routing_tileset" in rule and _routing_tileset() != rule["routing_tileset"]:
            continue
        if "times" in rule:
            if rule["times"] <= 0:
                continue
            rule["times"] -= 1
            rules_file.write_text(json.dumps(rules))
        return rule
    return None


def _side_effects(rule: dict[str, Any]) -> None:
    if "mkdir" in rule:
        (HOME / "volumes" / "overland_valhalla-data" / rule["mkdir"]).mkdir(parents=True, exist_ok=True)
    for relative, text in rule.get(
        "write", {}
    ).items():  # files that appear below the fake volume (a download's result)
        target = HOME / "volumes" / "overland_valhalla-data" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    if "kill_parent" in rule:
        os.kill(os.getppid(), getattr(signal, "SIG" + rule["kill_parent"]))
    if "sleep" in rule:
        time.sleep(rule["sleep"])


def _routing_tileset() -> str | None:
    """VALHALLA_TILESET of routing.env in the current directory (the install dir), if any."""
    routing = Path("routing.env")
    if not routing.is_file():
        return None
    for line in routing.read_text().splitlines():
        if line.startswith("VALHALLA_TILESET="):
            return line.split("=", 1)[1]
    return None


def _status_body() -> str:
    by_tileset = HOME / "status_by_tileset.json"
    modified = json.loads(by_tileset.read_text()).get(_routing_tileset() or "") if by_tileset.is_file() else None
    if modified is None:
        return VALHALLA_STATUS_OK
    return VALHALLA_STATUS_OK.replace("1793560782", str(modified))


def _answer(tool: str, argv: list[str], rule: dict[str, Any]) -> None:
    if tool == "gh" and "release_json" in rule and argv[:2] == ["run", "download"]:
        target = Path(argv[argv.index("--dir") + 1])
        target.mkdir(parents=True, exist_ok=True)
        (target / "release.json").write_text(json.dumps(rule["release_json"]))
    sys.stdout.write(rule.get("stdout", ""))
    sys.stderr.write(rule.get("stderr", ""))
    sys.exit(rule.get("exit", 0))


def _default(tool: str, argv: list[str], record: dict[str, Any]) -> None:
    handler = {
        "docker": _docker,
        "curl": _curl,
        "df": _df,
        "flock": _flock,
        "ssh": _ssh,
        "crontab": _crontab,
        "timeout": _timeout,
    }.get(tool)
    if handler is not None:
        handler(argv, record)
    sys.exit(0)


def _timeout(argv: list[str], record: dict[str, Any]) -> None:
    """`timeout SECONDS COMMAND...`: the call is recorded (the limit is part of the argv) and the command runs at once,
    with no clock: the offline tests check that the limit is asked for, not that it fires."""
    os.execvp(argv[1], argv[1:])  # noqa: S606 - the shim runs the shim of the next command


def _crontab(argv: list[str], record: dict[str, Any]) -> None:
    """The deploy user's schedule, kept in `$SHIM_HOME/crontab.txt`: `-l` lists it (exit 1 and the real message when the
    user has none), `<file>` (or `-` for stdin) replaces it with that text, `-r` removes it. A scripted rule can make
    any call fail; a `passthrough` rule with `stored_text` makes a replacement store that text instead (a write that
    reads back different)."""
    schedule = HOME / "crontab.txt"
    if argv == ["-l"]:
        if not schedule.is_file():
            sys.stderr.write("no crontab for user\n")
            sys.exit(1)
        sys.stdout.write(schedule.read_text())
    elif argv == ["-"]:
        schedule.write_text(sys.stdin.read())
    elif len(argv) == 1 and not argv[0].startswith("-"):
        stored = (MATCHED or {}).get("stored_text")
        schedule.write_text(stored if stored is not None else Path(argv[0]).read_text())
    elif argv == ["-r"]:
        schedule.unlink(missing_ok=True)
    else:
        sys.stderr.write(f"crontab shim: unsupported arguments {argv}\n")
        sys.exit(2)


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
    elif argv[:1] == ["run"] and _helper_mounts(argv):
        _helper(argv)
    elif argv[:1] == ["compose"] and "run" in argv and {"valhalla-fetch", "valhalla-build"} & set(argv):
        _compose_run(argv)
    elif argv[:1] == ["compose"] and "exec" in argv:
        print(_status_body())
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


def _compose_run(argv: list[str]) -> None:
    """`compose run` of the one-shot map-data services: their effect on the `build` subpath of the fake volume.

    valhalla-fetch: a download run leaves one extract per URL in build/src and default_speeds.json in build/ (the file
    the build service sees as /custom_files/default_speeds.json), a merge run leaves build/alps.osm.pbf.
    valhalla-build (the image's own entrypoint, not an `--entrypoint sh` run): needs build/alps.osm.pbf as the only
    *.pbf below build/ and leaves the four tileset files it makes in build/ (/custom_files). It has no network:
    without the default_speeds.json that valhalla-fetch put there it fails, as the image does when it must download
    the file. A scripted rule makes any of them fail first; a subpath that does not exist fails the mount, as it does
    in compose."""
    build = HOME / "volumes" / "overland_valhalla-data" / "build"
    if not build.is_dir():
        sys.stderr.write("error mounting volume subpath build: no such directory\n")
        sys.exit(1)
    joined = " ".join(argv)
    if "valhalla-fetch" in argv and "curl" in joined:
        (build / "src").mkdir(exist_ok=True)
        for url in (arg for arg in argv if arg.endswith(".osm.pbf")):
            (build / "src" / url.rsplit("/", 1)[-1]).write_text("extract\n")
        if "default_speeds.json" in joined:
            (build / "default_speeds.json").write_text("downloaded default_speeds.json\n")
    elif "valhalla-fetch" in argv and "osmium merge" in joined:
        (build / "alps.osm.pbf").write_text("merged\n")
    elif "valhalla-build" in argv and "--entrypoint" not in argv:
        others = [p for p in build.rglob("*.pbf") if p != build / "alps.osm.pbf"]
        if not (build / "alps.osm.pbf").is_file() or others:
            sys.stderr.write("valhalla-scripted: need exactly one pbf in /custom_files\n")
            sys.exit(1)
        if not (build / "default_speeds.json").is_file():
            sys.stderr.write("curl: (6) Could not resolve host: raw.githubusercontent.com\n")
            sys.exit(1)
        if not (build / "timezones.sqlite").is_file() or not (build / "timezones.sqlite").stat().st_size:
            sys.stderr.write("valhalla_build_timezones: curl failed for timezone-boundary-builder (no network)\n")
            sys.exit(1)  # the image downloads the time-zone db when none is there; the build has no network
        for name in ("valhalla_tiles.tar", "admins.sqlite", "valhalla.json"):
            (build / name).write_text(f"built {name}\n")
        os.utime(build / "valhalla_tiles.tar", (BUILD_TIME, BUILD_TIME))  # the tile build's own time


def _helper_mounts(argv: list[str]) -> dict[str, str]:
    """Mount destination -> host directory of a tile helper `docker run` (empty for any other `run`)."""
    mounts: dict[str, str] = {}
    for i, arg in enumerate(argv[:-1]):
        if arg == "-v":
            source, destination = argv[i + 1].split(":")[:2]
            if destination in HELPER_MOUNTS:
                host = source if source.startswith("/") else str(HOME / "volumes" / source)
                Path(host).mkdir(parents=True, exist_ok=True)
                mounts[destination] = host
    return mounts


def _helper(argv: list[str]) -> None:
    mounts = _helper_mounts(argv)
    start = next(i for i, arg in enumerate(argv) if arg == "sh" and argv[i + 1 : i + 2] == ["-c"])
    pattern = re.compile("(" + "|".join(mounts) + ")(?![A-Za-z0-9_-])")
    translated = [pattern.sub(lambda m: mounts[m.group(1)], arg) for arg in argv[start + 1 :]]
    sys.exit(subprocess.run(["sh", *translated], check=False).returncode)


def _ssh(argv: list[str], record: dict[str, Any]) -> None:
    if "-N" in argv:  # a port forward stays up until its owner kills it
        time.sleep(60)


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

"""Step 08-06: `make contract-live` on the Mac (D95, D164, D235), offline.

The real deploy/scripts/contract-live.sh runs with ssh and curl replaced by the shims of tests/deploy/shims and `uv`
by a fake written here that records the pytest run and exits as scripted. No Pi, no Docker, no engine.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.deploy.conftest import REPO, SHIMS

SCRIPT = REPO / "deploy/scripts/contract-live.sh"
PI_HOST = "deploy@pi.example"
PI_ADDRESS_PART = "pi.example"
FAKE_UV = """#!{python}
import json, os, sys
from pathlib import Path

home = Path(os.environ["SHIM_HOME"])
with (home / "calls.jsonl").open("a") as log:
    log.write(json.dumps({{"tool": "uv", "argv": sys.argv[1:], "stdin": ""}}) + "\\n")
sys.exit(int((home / "uv.exit").read_text()))
"""


class FakeMac:
    def __init__(self, root: Path) -> None:
        self.home = root / "shim"
        self.bin = root / "bin"
        for folder in (self.home, self.bin):
            folder.mkdir(parents=True)
        uv = self.bin / "uv"
        uv.write_text(FAKE_UV.format(python=sys.executable))
        uv.chmod(0o755)
        (self.home / "uv.exit").write_text("0")

    def rule(self, tool: str, *args_contain: str, **answer: Any) -> None:
        rules_file = self.home / "rules.json"
        rules = json.loads(rules_file.read_text()) if rules_file.exists() else []
        rules.append({"tool": tool, "args_contain": list(args_contain), **answer})
        rules_file.write_text(json.dumps(rules))

    def run(self) -> subprocess.CompletedProcess[str]:
        env = {key: value for key, value in os.environ.items() if not key.startswith(("PLANNER_", "PI_"))}
        env.update(
            PATH=f"{self.bin}{os.pathsep}{SHIMS}{os.pathsep}{os.environ['PATH']}",
            SHIM_HOME=str(self.home),
            PI_HOST=PI_HOST,
            PI_DIR="apps/overland-planner",
            WAIT_TIMEOUT="2",
        )
        return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120, check=False)

    def calls(self) -> list[dict[str, Any]]:
        log = self.home / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def index(self, tool: str, pattern: str) -> list[int]:
        return [
            i
            for i, call in enumerate(self.calls())
            if call["tool"] == tool and re.search(pattern, " ".join(call["argv"]))
        ]


def teardown_follows(mac: FakeMac) -> bool:
    (stop,), (remove,) = mac.index("ssh", r"\bstop\b.*valhalla-tunnel"), mac.index("ssh", r"\brm\b.*valhalla-tunnel")
    return stop < remove and bool(mac.index("ssh", r"-N -L"))


def shows_no_address(result: subprocess.CompletedProcess[str]) -> bool:
    return PI_ADDRESS_PART not in result.stdout + result.stderr


def test_the_tunnel_comes_up_the_engine_checks_run_through_it_and_everything_is_torn_down(tmp_path: Path) -> None:
    # bypass: the order of external calls of one run is wiring, a single example by nature.
    mac = FakeMac(tmp_path)

    result = mac.run()

    assert result.returncode == 0, result.stdout + result.stderr
    (marker,), (up,), (forward,), (status,), (pytest_run,) = (
        mac.index("ssh", r"test -f routing\.env"),
        mac.index("ssh", r"\bup\b.*valhalla-tunnel"),
        mac.index("ssh", r"-N -L"),
        mac.index("curl", r"127\.0\.0\.1:18002/status"),
        mac.index("uv", r"pytest"),
    )
    (stop,), (remove,) = mac.index("ssh", r"\bstop\b.*valhalla-tunnel"), mac.index("ssh", r"\brm\b.*valhalla-tunnel")
    assert marker < up < forward < status < pytest_run < stop < remove
    calls = mac.calls()
    assert calls[pytest_run]["argv"] == [
        "run",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--run-external",
        "tests/contract/routing_port",
        "--valhalla-url",
        "http://127.0.0.1:18002",
    ]
    ssh_forward = calls[forward]["argv"]
    assert ssh_forward[: ssh_forward.index("-N")] == [
        "-o",
        "BatchMode=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ConnectTimeout=10",
    ]
    assert ssh_forward[ssh_forward.index("-N") :] == ["-N", "-L", "18002:127.0.0.1:18002", PI_HOST]
    start = calls[up]["argv"][-1]
    assert "--profile ops" in start and "--profile routing" in start and "--env-file routing.env" in start
    assert "up -d --no-deps valhalla-tunnel" in start
    assert shows_no_address(result)


@pytest.mark.parametrize("failing", ["checks", "tunnel never answers"])
def test_the_tunnel_container_and_the_ssh_forward_are_removed_also_after_a_failure(
    tmp_path: Path, failing: str
) -> None:
    # bypass: two scripted failures of the wiring (the live checks fail, the engine never answers).
    mac = FakeMac(tmp_path)
    if failing == "checks":
        (mac.home / "uv.exit").write_text("1")
    else:
        mac.rule("curl", "127.0.0.1:18002/status", exit=7)

    result = mac.run()

    assert result.returncode != 0
    assert teardown_follows(mac)
    assert (mac.index("uv", r"pytest") != []) == (failing == "checks")
    assert shows_no_address(result)


def test_without_routing_env_on_the_pi_it_refuses_with_one_line_and_starts_nothing(tmp_path: Path) -> None:
    # bypass: one scripted answer of the Pi; the refusal path is wiring.
    mac = FakeMac(tmp_path)
    mac.rule("ssh", "test -f routing.env", exit=1)

    result = mac.run()

    assert result.returncode != 0
    assert [line for line in result.stderr.splitlines() if line.strip()] == [
        "make contract-live: routing.env does not exist on the Pi: run make tiles-seed first"
    ]
    assert len(mac.calls()) == 1 and shows_no_address(result)

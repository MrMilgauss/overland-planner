"""Step 08-07: `make acceptance-pi` on the Mac (D96, D236), offline.

The real deploy/scripts/acceptance-pi.sh runs with ssh and curl replaced by the shims of tests/deploy/shims and `uv`
by a fake that records the pytest run (and the credentials it was handed) and exits as scripted. No Pi, no Docker.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.deploy.conftest import REPO, SHIMS

SCRIPT = REPO / "deploy/scripts/acceptance-pi.sh"
PI_HOST = "deploy@pi.example"
USER, PASSWORD = "ferri", 'sh4red "family" pw'
FAKE_UV = """#!{python}
import json, os, sys
from pathlib import Path

home = Path(os.environ["SHIM_HOME"])
handed = (os.environ.get("PLANNER_PERF_USER"), os.environ.get("PLANNER_PERF_PASSWORD")) == ({user!r}, {password!r})
url = os.environ.get("PLANNER_PERF_URL")
record = {{"tool": "uv", "argv": sys.argv[1:], "stdin": "", "url": url, "handed": handed}}
with (home / "calls.jsonl").open("a") as log:
    log.write(json.dumps(record) + "\\n")
sys.exit(int((home / "uv.exit").read_text()))
"""


class FakeMac:
    def __init__(self, root: Path) -> None:
        self.home = root / "shim"
        self.bin = root / "bin"
        for folder in (self.home, self.bin):
            folder.mkdir(parents=True)
        uv = self.bin / "uv"
        uv.write_text(FAKE_UV.format(python=sys.executable, user=USER, password=PASSWORD))
        uv.chmod(0o755)
        (self.home / "uv.exit").write_text("0")
        self.rule("ssh", "PLANNER_BASIC_AUTH_USER", stdout=f"{USER}\n{PASSWORD}\n")

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


def test_planner_perf_comes_up_on_valhalla_the_live_scenarios_run_through_the_tunnel_and_it_is_removed(
    tmp_path: Path,
) -> None:
    # bypass: the order of external calls of one run is wiring, a single example by nature.
    mac = FakeMac(tmp_path)

    result = mac.run()

    assert result.returncode == 0, result.stdout + result.stderr
    (marker,), (up,), (forward,), (healthy,), (pytest_run,) = (
        mac.index("ssh", r"test -f routing\.env$"),
        mac.index("ssh", r"\bup\b.*planner-perf"),
        mac.index("ssh", r"-N -L"),
        mac.index("curl", r"127\.0\.0\.1:18080/healthz"),
        mac.index("uv", r"pytest"),
    )
    (stop,), (remove,) = mac.index("ssh", r"\bstop\b.*planner-perf"), mac.index("ssh", r"\brm\b.*planner-perf")
    assert marker < up < forward < healthy < pytest_run < stop < remove
    calls = mac.calls()
    assert "PERF_ROUTING_PROVIDER=valhalla" in calls[up]["argv"][-1]
    assert calls[pytest_run]["argv"] == [
        "run",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--run-external",
        "--run-pending=slice-06a",
        "-m",
        "pi and real_provider",
        "tests/acceptance/overland_route_planner_mvp",
    ]
    assert calls[pytest_run]["url"] == "http://127.0.0.1:18080" and calls[pytest_run]["handed"]
    assert all("ConnectTimeout=10" in call["argv"] for call in calls if call["tool"] == "ssh")
    shown = result.stdout + result.stderr + json.dumps([call["argv"] for call in calls])
    assert USER not in shown and PASSWORD not in shown and "pi.example" not in result.stdout + result.stderr
    assert not any("planner-data" in " ".join(call["argv"]) for call in calls)


def test_a_failing_scenario_exits_non_zero_and_planner_perf_is_still_removed(tmp_path: Path) -> None:
    # bypass: one scripted failure of the live scenarios.
    mac = FakeMac(tmp_path)
    (mac.home / "uv.exit").write_text("1")

    result = mac.run()

    assert result.returncode != 0
    assert mac.index("ssh", r"\bstop\b.*planner-perf") and mac.index("ssh", r"\brm\b.*planner-perf")


def test_it_refuses_when_routing_env_is_missing_on_the_pi_and_starts_nothing(tmp_path: Path) -> None:
    # bypass: one scripted answer of the Pi.
    mac = FakeMac(tmp_path)
    mac.rule("ssh", "test -f routing.env", exit=1)

    result = mac.run()

    assert result.returncode != 0 and "routing.env" in result.stderr and "make tiles-seed" in result.stderr
    assert mac.index("ssh", r"\bup\b") == [] and mac.index("uv", r".") == []

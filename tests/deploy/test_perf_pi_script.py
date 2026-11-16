"""Step 06-05: `make perf-pi` on the Mac (D96, D147, D164, D175, D177), offline.

The real deploy/scripts/perf-pi.sh runs with ssh, rsync and curl replaced by the shims of tests/deploy/shims and `uv`
by a fake written here: its `uv run pytest` answers like the golden check and the @pi scenarios would (appending the
measured runs to PERF_REPORT), and its `uv run python -m tests.perf.perf_pi report` runs the real report. The fake
Pi answers the credential read with the household user and password; nothing may show them.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.common.state_delta import assert_state_delta, unchanged
from tests.deploy.conftest import REPO, SHIMS, routing_profile_on

SCRIPT = REPO / "deploy/scripts/perf-pi.sh"
PERF_SERVICE = "planner-perf"
USER_VOLUME = "overland_planner-data"
COMPOSE_VERB = re.compile(r"\$PERF_COMPOSE|docker compose")
MUTATING = re.compile(r"\b(up|stop|rm|down|restart|kill|run|create)\b")
FAKE_UV = '''#!{python}
"""Fake `uv` for the perf-pi tests: records each call (never the credential values) and answers it."""
import json, os, subprocess, sys
from pathlib import Path

home = Path(os.environ["SHIM_HOME"])
argv = sys.argv[1:]
env = {{key: os.environ.get(key) for key in ("GOLDEN_INSTANCE", "PLANNER_PERF_URL", "PERF_REPORT")}}
expected = json.loads((home / "credentials.json").read_text())
env["credentials_handed_over"] = (
    os.environ.get("PLANNER_PERF_USER"), os.environ.get("PLANNER_PERF_PASSWORD")
) == (expected["user"], expected["password"])
with (home / "calls.jsonl").open("a") as log:
    log.write(json.dumps({{"tool": "uv", "argv": argv, "env": env, "stdin": ""}}) + "\\n")
answers = json.loads((home / "uv.json").read_text())
joined = " ".join(argv)
if argv[:2] == ["run", "pytest"]:
    mode = "golden " + (env["GOLDEN_INSTANCE"] or "") if "golden_order" in joined else "pi"
    answer = answers.get(mode, {{"exit": 0}})
    if mode == "pi" and env["PERF_REPORT"]:
        with open(env["PERF_REPORT"], "a") as runs:
            for solve_ms in answers.get("solve_ms", []):
                stages = {{"snapshot": 5, "matrix": 40, "reach_model": 10, "solve": solve_ms, "guard_persist": 300}}
                runs.write(json.dumps({{"state": "done", "stage_ms": stages}}) + "\\n")
    sys.exit(answer["exit"])
if "tests.perf.perf_pi" in joined and "measure" in argv:
    out = Path(argv[argv.index("--out") + 1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({{"runs": [], "verdict": None}}))
    sys.exit(answers.get("measure", {{"exit": 0}})["exit"])
if argv[:2] == ["run", "python"]:
    sys.exit(subprocess.run([sys.executable, *argv[2:]]).returncode)
sys.exit(0)
'''
GATE_SOLVE_MS = [41_000 + 1_000 * k for k in range(10)]


class FakeMac:
    """The Mac side: shims on PATH, a fake Pi behind ssh that holds `user` and `password` in its .env."""

    def __init__(self, root: Path, user: str = "ferri", password: str = 'sh4red "family" pw') -> None:  # noqa: S107
        self.root = root
        self.home = root / "shim"
        self.bin = root / "bin"
        self.out = root / "perf"
        for folder in (self.home, self.bin):
            folder.mkdir(parents=True)
        uv = self.bin / "uv"
        uv.write_text(FAKE_UV.format(python=sys.executable))
        uv.chmod(0o755)
        self.user, self.password = user, password
        (self.home / "credentials.json").write_text(json.dumps({"user": user, "password": password}))
        self.answers: dict[str, Any] = {"solve_ms": GATE_SOLVE_MS}
        self.rule("ssh", "PLANNER_BASIC_AUTH_USER", stdout=f"{user}\n{password}\n")

    def rule(self, tool: str, *args_contain: str, **answer: Any) -> None:
        rules_file = self.home / "rules.json"
        rules = json.loads(rules_file.read_text()) if rules_file.exists() else []
        rules.append({"tool": tool, "args_contain": list(args_contain), **answer})
        rules_file.write_text(json.dumps(rules))

    def run(self, **variables: str) -> subprocess.CompletedProcess[str]:
        (self.home / "uv.json").write_text(json.dumps(self.answers))
        env = {key: value for key, value in os.environ.items() if not key.startswith(("PLANNER_", "PERF_", "GOLDEN"))}
        env.update(
            PATH=f"{self.bin}{os.pathsep}{SHIMS}{os.pathsep}{os.environ['PATH']}",
            SHIM_HOME=str(self.home),
            PI_HOST="deploy@pi.example",
            PI_DIR="apps/overland-planner",
            PERF_OUT_DIR=str(self.out),
            **variables,
        )
        return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120)

    def calls(self, tool: str | None = None) -> list[dict[str, Any]]:
        log = self.home / "calls.jsonl"
        records = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [record for record in records if tool is None or record["tool"] == tool]

    def reports(self) -> list[dict[str, Any]]:
        return [json.loads(path.read_text()) for path in sorted(self.out.glob("*.json"))] if self.out.is_dir() else []


def remote_commands(mac: FakeMac) -> list[str]:
    return [call["argv"][-1] for call in mac.calls("ssh")]


def compose(mac: FakeMac, verb: str) -> list[int]:
    """Indexes, among all calls, of the ssh calls whose remote command runs `compose <verb>` on planner-perf."""
    return [
        i
        for i, call in enumerate(mac.calls())
        if call["tool"] == "ssh" and re.search(rf"\b{verb}\b.*\b{PERF_SERVICE}\b", call["argv"][-1])
    ]


def uv_index(mac: FakeMac, predicate: Any) -> list[int]:
    return [i for i, call in enumerate(mac.calls()) if call["tool"] == "uv" and predicate(call)]


def golden(instance: str) -> Any:
    return lambda call: "golden_order" in call["argv"] and call["env"]["GOLDEN_INSTANCE"] == instance


def measured(call: dict[str, Any]) -> bool:
    return "-m" in call["argv"] and "pi" in call["argv"] and "golden_order" not in call["argv"]


def test_gate_run_checks_both_golden_orders_then_measures_and_always_takes_planner_perf_down(tmp_path: Path) -> None:
    # bypass: the order of external calls of one run is wiring, a single example by nature.
    mac = FakeMac(tmp_path)

    result = mac.run()

    assert result.returncode == 0, result.stdout + result.stderr
    ups = compose(mac, "up")
    commands = [mac.calls()[i]["argv"][-1] for i in ups]
    assert len(ups) == 3 and "PERF_MOCK_PLAN=/perf/i2-sparse.road-map.yaml" in commands[1]
    assert all("PERF_MOCK_PLAN= " in command for command in (commands[0], commands[2])), "default road map"
    copied = [i for i, c in enumerate(mac.calls()) if c["tool"] == "rsync" and "i2-sparse.road-map.yaml" in str(c)]
    (i1,), (i2,), (pi_run,) = uv_index(mac, golden("i1")), uv_index(mac, golden("i2")), uv_index(mac, measured)
    (stop,), (remove,) = compose(mac, "stop"), compose(mac, "rm")
    assert ups[0] < i1 < copied[0] < ups[1] < i2 < ups[2] < pi_run < stop < remove
    assert all(
        c["env"]["PLANNER_PERF_URL"] == "http://127.0.0.1:18080" for c in mac.calls("uv") if "pytest" in c["argv"]
    )
    assert all(c["env"]["credentials_handed_over"] for c in mac.calls("uv") if "pytest" in c["argv"])
    tunnel = [c for c in mac.calls("ssh") if "-L" in c["argv"]]
    assert tunnel and tunnel[0]["argv"][tunnel[0]["argv"].index("-L") + 1] == "18080:127.0.0.1:18080"
    (report,) = mac.reports()
    assert report["verdict"] == "pass" and len(report["runs"]) == 10
    assert report["slowest_ms"]["solve"] == max(GATE_SOLVE_MS)


def test_a_golden_mismatch_stops_before_any_measurement_and_still_takes_planner_perf_down(tmp_path: Path) -> None:
    # bypass: one scripted golden failure is a wiring check of the stop-early path.
    mac = FakeMac(tmp_path)
    mac.answers["golden i1"] = {"exit": 1}

    result = mac.run()

    assert result.returncode != 0
    assert "golden" in result.stderr and "i1" in result.stderr
    assert uv_index(mac, golden("i2")) == [] and uv_index(mac, measured) == [] and mac.reports() == []
    assert compose(mac, "stop") and compose(mac, "rm")


def test_a_missed_gate_exits_non_zero_with_the_report_written(tmp_path: Path) -> None:
    # bypass: the scenario failing (slowest solve over 55 s) is one scripted answer of the fake pytest.
    mac = FakeMac(tmp_path)
    mac.answers |= {"pi": {"exit": 1}, "solve_ms": [*GATE_SOLVE_MS[:9], 56_000]}

    result = mac.run()

    assert result.returncode != 0
    (report,) = mac.reports()
    assert report["verdict"] == "fail" and report["slowest_ms"]["solve"] == 56_000
    assert compose(mac, "stop") and compose(mac, "rm")


def test_other_modes_measure_through_perf_pi_without_the_scenarios(tmp_path: Path) -> None:
    # bypass: which program a mode runs is wiring; N=30 ITEMS=70 (D146) is the representative non-gate mode.
    mac = FakeMac(tmp_path)

    result = mac.run(N="30", ITEMS="70")

    assert result.returncode == 0, result.stdout + result.stderr
    assert uv_index(mac, measured) == []
    (measure,) = [c for c in mac.calls("uv") if "measure" in c["argv"]]
    argv = measure["argv"]
    assert argv[argv.index("--n") + 1] == "30" and argv[argv.index("--items") + 1] == "70"
    assert "--points" not in argv and measure["env"]["credentials_handed_over"]


secret_text = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126, blacklist_characters="\"'\\$`"), min_size=4, max_size=16
).map(lambda text: f"Zq{text}")  # a prefix no script output, path or JSON key carries


@given(user=secret_text, password=secret_text)
@settings(max_examples=5, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_credentials_never_show_and_the_users_planner_is_never_mutated(
    user: str, password: str, tmp_path_factory: Any
) -> None:
    mac = FakeMac(tmp_path_factory.mktemp("mac"), user=user, password=password)
    before = {"exit_code": 0, "credentials_shown": False, "user_planner_mutated": False, "reports": 1}

    result = mac.run()

    shown = result.stdout + result.stderr + json.dumps(mac.reports()) + json.dumps([c["argv"] for c in mac.calls()])
    mutating = [
        command for command in remote_commands(mac) if COMPOSE_VERB.search(command) and MUTATING.search(command)
    ]
    after = {
        "exit_code": result.returncode,
        "credentials_shown": user in shown or password in shown,
        "user_planner_mutated": any(USER_VOLUME in command or PERF_SERVICE not in command for command in mutating),
        "reports": len(mac.reports()),
    }
    assert_state_delta(
        before,
        after,
        universe={"exit_code", "credentials_shown", "user_planner_mutated", "reports"},
        expected={key: unchanged() for key in before},
        strict=True,
    )


@pytest.mark.parametrize("routing_env", [False, True], ids=["without routing.env", "with routing.env"])
def test_the_perf_compose_turns_the_routing_profile_on_exactly_when_routing_env_exists(
    tmp_path: Path, routing_env: bool
) -> None:
    # bypass: the remote command string is wiring; it runs here in a fake install dir against the docker shim.
    mac = FakeMac(tmp_path)
    assert mac.run().returncode == 0
    (up, *_) = [c["argv"][-1] for c in mac.calls("ssh") if re.search(r"\bup\b.*\bplanner-perf\b", c["argv"][-1])]
    install = tmp_path / "apps" / "overland-planner"  # the PI_DIR the remote command changes into
    install.mkdir(parents=True)
    (install / "release.env").write_text("PLANNER_IMAGE=x\n")
    if routing_env:
        (install / "routing.env").write_text("VALHALLA_TILESET=2026-10\n")
    shim = tmp_path / "docker-home"
    shim.mkdir()

    subprocess.run(
        ["bash", "-c", up],
        cwd=tmp_path,
        env=os.environ | {"PATH": f"{SHIMS}{os.pathsep}{os.environ['PATH']}", "SHIM_HOME": str(shim)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    (compose_call,) = [json.loads(line)["argv"] for line in (shim / "calls.jsonl").read_text().splitlines()]
    assert routing_profile_on(compose_call) == routing_env
    assert ("--profile", "perf") in itertools.pairwise(compose_call)

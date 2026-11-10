"""The acceptance teardown ends what a planner process left running (review F5).

Integration level: one real process tree. A parent spawns a multiprocessing child, as the planner spawns its solve
children, and is then killed abruptly, as `ServerPlanner.kill_abruptly` does: the child outlives it. What the teardown
recorded before the kill is ended afterwards; the scenario that proves the PRODUCT ends its children checks before.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from tests.acceptance.overland_route_planner_mvp.steps.planner import LeftBehind

_PARENT = """
import multiprocessing
import time


def search() -> None:
    time.sleep(60)


if __name__ == "__main__":
    child = multiprocessing.get_context("spawn").Process(target=search)
    child.start()
    print(child.pid, flush=True)
    time.sleep(60)
"""
GONE_WITHIN_S = 5.0


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while _is_running(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not _is_running(pid)


def test_the_teardown_ends_a_spawned_child_that_outlived_its_killed_parent(tmp_path: Path) -> None:
    script = tmp_path / "planner_like_parent.py"
    script.write_text(_PARENT)
    parent = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    child_pid = None
    try:
        assert parent.stdout is not None
        child_pid = int(parent.stdout.readline())
        left_behind = LeftBehind()
        left_behind.record(parent.pid)
        parent.kill()
        parent.wait()
        assert _is_running(child_pid), "precondition: the spawned child outlives its killed parent"

        left_behind.reap()

        assert _gone_within(child_pid, GONE_WITHIN_S), f"child {child_pid} still running after the teardown"
    finally:
        parent.kill()
        parent.wait()
        if child_pid is not None and _is_running(child_pid):
            os.kill(child_pid, signal.SIGKILL)

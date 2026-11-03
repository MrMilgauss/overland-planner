"""Regression (03-02 addendum a): pytest run from a git hook must not let git-using tests act on the hook's repository.

A pre-push hook in a linked worktree exports GIT_DIR / GIT_INDEX_FILE / GIT_WORK_TREE; one such run flipped
`core.bare=true` in the main repository. The suite-wide fixture in tests/conftest.py removes those variables.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GIT_USING_TESTS = ("tests/ci/test_repo_hygiene.py", "tests/deploy/test_rollback_script.py")


def test_git_using_tests_ignore_the_calling_hooks_repository(tmp_path: Path) -> None:
    scratch = tmp_path / "hook-repo.git"
    subprocess.run(["git", "init", "-q", "--bare", str(scratch)], check=True)
    config_before = (scratch / "config").read_text()
    hook_env = {
        **os.environ,
        "GIT_DIR": str(scratch),
        "GIT_INDEX_FILE": str(scratch / "index"),
        "GIT_WORK_TREE": str(tmp_path),
    }

    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *GIT_USING_TESTS],
        cwd=REPO_ROOT,
        env=hook_env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-2000:]
    assert ((scratch / "config").read_text(), sorted(p.name for p in scratch.iterdir() if p.name == "index")) == (
        config_before,
        [],
    )

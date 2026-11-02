"""Static contract of the CI pipeline (slice 00a; D85, D86, D161, D162, D168, D169, D170, D178).

`.github/workflows/ci.yml` and `.github/dependabot.yml` are parsed with PyYAML and checked against the DEVOPS CI
table. Step 01-07 covers the commit stage (jobs 1 lint, 2 test-python, 4 test-web) plus the docs-only filter;
steps 01-08/01-09 extend `JOB_RUNNERS` and add their own checks for the image, e2e and publish jobs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"

RUNNER = "ubuntu-24.04"  # D178
COMMIT_STAGE = ("lint", "test-python", "test-web")
# Every job of ci.yml and its runner; later steps add jobs 5-9 here.
JOB_RUNNERS = {"changes": RUNNER, "lint-docs": RUNNER, **dict.fromkeys(COMMIT_STAGE, RUNNER)}
USES = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\S+)(?P<comment>.*)$", re.MULTILINE)
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
TAG_COMMENT = re.compile(r"#\s*v\d")


def _workflow() -> dict[Any, Any]:
    assert WORKFLOW.is_file(), ".github/workflows/ci.yml missing"
    loaded = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(loaded, dict), "ci.yml is not a mapping"
    return loaded


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the bare key `on` as boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), "ci.yml has no `on:` mapping"
    return triggers


def _job(workflow: dict[Any, Any], name: str) -> dict[str, Any]:
    jobs = workflow.get("jobs") or {}
    assert name in jobs, f"job {name!r} missing from ci.yml"
    job: dict[str, Any] = jobs[name]
    return job


def _needs(job: dict[str, Any]) -> set[str]:
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def _runs(job: dict[str, Any]) -> list[str]:
    return [step.get("run", "") for step in job.get("steps", [])]


def _index(job: dict[str, Any], fragment: str) -> int:
    for position, script in enumerate(_runs(job)):
        if fragment in script:
            return position
    raise AssertionError(f"no step runs {fragment!r}")


def _main_pytest(job: dict[str, Any]) -> dict[str, Any]:
    steps = [s for s in job["steps"] if "pytest" in s.get("run", "") and "not walking_skeleton" in s["run"]]
    assert len(steps) == 1, "test-python needs exactly one main pytest step excluding the walking skeleton"
    return steps[0]


def test_commit_stage_jobs_run_on_every_push() -> None:
    workflow = _workflow()
    triggers = _triggers(workflow)

    assert set(triggers) == {"push", "pull_request", "workflow_dispatch"}
    assert not (triggers["push"] or {}).get("branches"), "push must run on every branch"
    assert triggers["pull_request"]["branches"] == ["main"]
    assert workflow["concurrency"]["group"] == "ci-${{ github.ref }}"
    assert "refs/heads/main" in str(workflow["concurrency"]["cancel-in-progress"])

    assert {name: job.get("runs-on") for name, job in workflow["jobs"].items()} == JOB_RUNNERS
    for name in COMMIT_STAGE:
        assert _needs(_job(workflow, name)) <= {"changes"}, f"{name} must run in parallel with the commit stage"

    refs = [(m["ref"], m["comment"]) for m in USES.finditer(WORKFLOW.read_text())]
    assert refs, "ci.yml uses no actions"
    unpinned = [ref for ref, comment in refs if not (PINNED.match(ref) and TAG_COMMENT.search(comment))]
    assert unpinned == [], f"actions not pinned by commit SHA with a tag comment: {unpinned}"


def test_test_python_builds_web_before_pytest_and_passes_pending_flags() -> None:
    workflow = _workflow()
    job = _job(workflow, "test-python")
    env = {**workflow.get("env", {}), **job.get("env", {})}
    pytest_step = _main_pytest(job)

    assert workflow["env"]["PENDING_FLAGS"] == ""
    assert _index(job, "vite build") < _index(job, "df -T") < job["steps"].index(pytest_step)
    assert _index(job, "npm ci") <= _index(job, "vite build")
    assert '"$DATA_DIR"' in _runs(job)[_index(job, "df -T")]
    for name in ("DATA_DIR", "PLANNER_TEST_WORKSPACE"):
        assert str(env[name]).startswith("${{ github.workspace }}/"), f"{name} must live under the workspace"
    assert env["HYPOTHESIS_PROFILE"] == "ci"

    command = pytest_step["run"]
    assert "$PENDING_FLAGS" in command
    assert "not real_provider and not pi and not walking_skeleton" in command
    assert "--cov-fail-under=80" in command
    assert not pytest_step.get("continue-on-error")


def test_walking_skeleton_step_is_non_blocking_until_slice_01a() -> None:
    workflow = _workflow()
    steps = [
        s
        for s in _job(workflow, "test-python")["steps"]
        if "pytest" in s.get("run", "") and re.search(r"-m\s+\"?walking_skeleton\b", s["run"])
    ]

    assert len(steps) == 1, "test-python needs exactly one walking-skeleton pytest step"
    assert steps[0]["continue-on-error"] is True
    assert "$PENDING_FLAGS" in steps[0]["run"]
    blocking = [
        (name, step.get("name"))
        for name in COMMIT_STAGE
        for step in _job(workflow, name)["steps"]
        if step.get("continue-on-error") and step is not steps[0]
    ]
    assert blocking == [], f"only the walking skeleton may be non-blocking: {blocking}"


LINT_GATES = (
    "uv lock --check",
    "ruff format --check",
    "ruff check",
    "mypy",
    "lint-imports",
    "gitleaks git",
    "hadolint Dockerfile",
    "actionlint",
    "npm run check",  # svelte-check --fail-on-warnings
    "eslint",
    "prettier --check",
    "pip-audit",
    "npm audit --omit=dev --audit-level=high",
)


def test_lint_blocks_on_every_static_gate() -> None:
    steps = _job(_workflow(), "lint")["steps"]
    blocking = [s.get("run", "") for s in steps if not s.get("continue-on-error")]

    missing = [gate for gate in LINT_GATES if not any(gate in script for script in blocking)]
    assert missing == [], f"lint does not block on: {missing}"


def test_docs_only_pushes_run_only_markdown_lint() -> None:
    workflow = _workflow()
    changes = _job(workflow, "changes")
    filter_script = "\n".join(_runs(changes))

    assert workflow["permissions"] == {"contents": "read"}
    assert "^docs/" in filter_script and r"\.md$" in filter_script
    for name in COMMIT_STAGE:
        assert _job(workflow, name)["if"] == "needs.changes.outputs.code == 'true'", f"{name} skips docs-only pushes"
    assert "changes" in _needs(_job(workflow, "lint-docs"))
    assert any("markdownlint-cli2" in str(s.get("uses", "")) for s in _job(workflow, "lint-docs")["steps"])


def test_dependabot_updates_every_ecosystem_weekly_in_groups() -> None:
    assert DEPENDABOT.is_file(), ".github/dependabot.yml missing"
    updates = yaml.safe_load(DEPENDABOT.read_text())["updates"]

    assert {u["package-ecosystem"] for u in updates} == {"github-actions", "uv", "npm", "docker"}
    for update in updates:
        assert update["schedule"]["interval"] == "weekly"
        assert update.get("groups"), f"{update['package-ecosystem']} updates are not grouped"

"""Static contract of the CI pipeline (slice 00a; D85, D86, D161, D162, D168, D169, D170, D178).

`.github/workflows/ci.yml` and `.github/dependabot.yml` are parsed with PyYAML and checked against the DEVOPS CI
table. Step 01-07 covers the commit stage (jobs 1 lint, 2 test-python, 4 test-web) plus the docs-only filter; step 01-08
the image jobs 5 image-amd64 and 6 image-arm64 and `.github/scripts/image-smoke.sh`; step 01-09 extends
`JOB_RUNNERS` again for the e2e and publish jobs.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
IMAGE_SMOKE = REPO_ROOT / ".github" / "scripts" / "image-smoke.sh"

RUNNER = "ubuntu-24.04"  # D178
COMMIT_STAGE = ("lint", "test-python", "test-web")
# Every job of ci.yml and its runner; later steps add jobs 5-9 here.
IMAGE_JOBS = ("image-amd64", "image-arm64")
ARM64_RUNNER = "${{ vars.ARM64_RUNNER || 'ubuntu-24.04' }}"  # QEMU on the hosted runner unless a native one is set
JOB_RUNNERS = {
    "changes": RUNNER,
    "lint-docs": RUNNER,
    **dict.fromkeys(COMMIT_STAGE, RUNNER),
    "image-amd64": RUNNER,
    "image-arm64": ARM64_RUNNER,
}
MAIN_PUSH = "github.event_name == 'push' && github.ref == 'refs/heads/main'"
IMAGE = "ghcr.io/mrmilgauss/overland-planner"
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


def _uses(job: dict[str, Any], action: str) -> list[dict[str, Any]]:
    return [step for step in job["steps"] if str(step.get("uses", "")).startswith(f"{action}@")]


def _writes_to_registry(step: dict[str, Any]) -> bool:
    uses = str(step.get("uses", ""))
    if uses.startswith(("docker/login-action@", "actions/attest-build-provenance@")):
        return True
    if uses.startswith("docker/build-push-action@"):
        build = step.get("with", {})
        return build.get("push") is True or "push=true" in str(build.get("outputs", ""))
    return "docker push" in step.get("run", "") or "imagetools create" in step.get("run", "")


def test_image_jobs_push_by_digest_only_on_main() -> None:
    workflow = _workflow()

    for name, scope in zip(IMAGE_JOBS, ("amd64", "arm64"), strict=True):
        job = _job(workflow, name)
        assert {"lint", "test-python", "test-web"} <= _needs(job), f"{name} must wait for the commit stage"
        assert job["if"] == f"({MAIN_PUSH}) || github.event_name == 'workflow_dispatch'", f"{name} on main/manual only"

        builds = _uses(job, "docker/build-push-action")
        assert builds, f"{name} has no buildx build"
        for build in builds:
            settings = build["with"]
            assert settings["platforms"] == f"linux/{scope}"
            assert settings["cache-from"] == f"type=gha,scope={scope}", f"{name} must read its own gha cache"
            assert "GIT_SHA=" in settings["build-args"] and "COMMIT_TS=" in settings["build-args"]
            assert "ALEMBIC_HEAD=" in settings["build-args"]

        writers = [step for step in job["steps"] if _writes_to_registry(step)]
        assert {str(step.get("uses", "")).split("@")[0] for step in writers} >= {
            "docker/login-action",
            "docker/build-push-action",
            "actions/attest-build-provenance",
        }, f"{name} must log in, push and attest on main"
        unguarded = [step.get("name", step.get("uses")) for step in writers if step.get("if") != MAIN_PUSH]
        assert unguarded == [], f"{name} writes to GHCR outside main pushes: {unguarded}"

        pushes = [b for b in builds if _writes_to_registry(b)]
        assert len(pushes) == 1, f"{name} pushes exactly once"
        push = pushes[0]
        assert f"name={IMAGE}" in push["with"]["outputs"] and "push-by-digest=true" in push["with"]["outputs"]
        assert push["with"]["sbom"] is True and "mode=max" in str(push["with"]["provenance"])
        assert any(f"type=gha,scope={scope}" in str(b["with"].get("cache-to", "")) for b in builds)

        attest = _uses(job, "actions/attest-build-provenance")[0]["with"]
        assert attest["subject-name"] == IMAGE and attest["push-to-registry"] is True
        assert attest["subject-digest"] == f"${{{{ steps.{push['id']}.outputs.digest }}}}"
        assert job["outputs"]["digest"] == f"${{{{ steps.{push['id']}.outputs.digest }}}}", "publish (01-09) needs it"

    qemu = _uses(_job(workflow, "image-arm64"), "docker/setup-qemu-action")
    assert len(qemu) == 1 and "ARM64" in qemu[0]["if"], "QEMU only when the runner is not native arm64"


def test_amd64_image_artifact_and_trivy_scans() -> None:
    workflow = _workflow()
    amd64 = _job(workflow, "image-amd64")

    exports = [b for b in _uses(amd64, "docker/build-push-action") if not _writes_to_registry(b)]
    assert len(exports) == 1 and not exports[0].get("if"), "the amd64 tarball is built on every image run"
    assert exports[0]["with"]["outputs"] == "type=docker,dest=/tmp/planner-amd64.tar"
    upload = _uses(amd64, "actions/upload-artifact")
    assert len(upload) == 1 and not upload[0].get("if")
    assert upload[0]["with"]["name"] == "planner-image-amd64"
    assert upload[0]["with"]["path"] == "/tmp/planner-amd64.tar.zst"
    assert upload[0]["with"]["retention-days"] == 1
    assert "zstd" in _runs(amd64)[_index(amd64, "planner-amd64.tar.zst")]

    for name in IMAGE_JOBS:
        job = _job(workflow, name)
        scripts = [s for s in _runs(job) if "trivy image" in s]
        blocking = [
            s for s in scripts if "--severity CRITICAL" in s and "--ignore-unfixed" in s and "--exit-code 1" in s
        ]
        reporting = [s for s in scripts if "--severity HIGH" in s and "--exit-code 0" in s]
        assert blocking and reporting, f"{name}: fixable CRITICAL must fail, HIGH must be reported"
        assert all("--scanners vuln,secret" in s for s in scripts), f"{name} scans vulnerabilities and secrets"
        sizes = [s for s in _runs(job) if ".tar.zst" in s and "GITHUB_STEP_SUMMARY" in s]
        assert sizes, f"{name} records the compressed image size in the job summary (D169)"


def test_arm64_smoke_checks_healthz_and_solver_probe() -> None:
    job = _job(_workflow(), "image-arm64")
    loads = [b for b in _uses(job, "docker/build-push-action") if b["with"].get("load") is True]
    assert len(loads) == 1 and not loads[0].get("if"), "the smoke needs the arm64 image loaded on every run"

    smoke = [s for s in job["steps"] if ".github/scripts/image-smoke.sh" in s.get("run", "")]
    assert len(smoke) == 1 and not smoke[0].get("continue-on-error")
    assert _index(job, "image-smoke.sh") < job["steps"].index(
        next(b for b in job["steps"] if _writes_to_registry(b) and "build-push-action" in str(b.get("uses")))
    ), "the image is pushed only after the smoke passed"
    assert "180" in str(smoke[0].get("env", {})), "QEMU allows 180 s to answer /healthz"

    assert IMAGE_SMOKE.is_file(), ".github/scripts/image-smoke.sh missing"
    script = IMAGE_SMOKE.read_text()
    assert script.startswith("#!/usr/bin/env bash\n") and "set -euo pipefail" in script
    for fragment in (
        "docker run",
        "--platform linux/arm64",
        "--init",
        "-m 1g",
        "ROUTING_PROVIDER=mock",
        ':/data"',
        "/healthz",
        "/api/health",
        "tour_solver",
        "import ortools",
        "docker logs",
    ):
        assert fragment in script, f"image-smoke.sh lacks {fragment!r}"
    syntax = subprocess.run(["bash", "-n", str(IMAGE_SMOKE)], capture_output=True, text=True, check=False)
    assert syntax.returncode == 0, syntax.stderr


def test_image_jobs_have_job_level_package_permissions() -> None:
    workflow = _workflow()

    assert workflow["permissions"] == {"contents": "read"}, "write scopes live on the image jobs only (D161)"
    for name in IMAGE_JOBS:
        assert _job(workflow, name)["permissions"] == {
            "contents": "read",
            "packages": "write",
            "id-token": "write",
            "attestations": "write",
        }, f"{name} permissions"
    for name, job in workflow["jobs"].items():
        if name not in IMAGE_JOBS:
            assert "permissions" not in job, f"{name} must inherit read-only permissions"

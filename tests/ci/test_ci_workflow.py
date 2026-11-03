"""Static contract of the CI pipeline (slice 00a; D85, D86, D161, D162, D168, D169, D170, D178).

`.github/workflows/ci.yml` and `.github/dependabot.yml` are parsed with PyYAML and checked against the DEVOPS CI
table. Step 01-07 covers the commit stage (jobs 1 lint, 2 test-python, 4 test-web) plus the docs-only filter; step 01-08
the image jobs 5 image-amd64 and 6 image-arm64 and `.github/scripts/image-smoke.sh`; step 01-09 the jobs 7 e2e,
8 mutation and 9 publish, their scripts (`pytest-selection.sh`, `ghcr_prune.py`) and `.github/workflows/weekly.yml`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
WEEKLY = REPO_ROOT / ".github" / "workflows" / "weekly.yml"
IMAGE_SMOKE = REPO_ROOT / ".github" / "scripts" / "image-smoke.sh"
PYTEST_SELECTION = REPO_ROOT / ".github" / "scripts" / "pytest-selection.sh"
GHCR_PRUNE = REPO_ROOT / ".github" / "scripts" / "ghcr_prune.py"

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
    "e2e": RUNNER,
    "mutation": RUNNER,
    "publish": RUNNER,
}
REGISTRY_WRITERS = (*IMAGE_JOBS, "publish")  # D161
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
    steps = [s for s in job["steps"] if "pytest" in s.get("run", "") and "--cov-fail-under" in s["run"]]
    assert len(steps) == 1, "test-python needs exactly one main (coverage-gated) pytest step"
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

    assert workflow["env"]["PENDING_FLAGS"] == "--run-pending=slice-00b"  # D170: slice 00b is GREEN (step 02-07)
    assert _index(job, "vite build") < _index(job, "df -T") < job["steps"].index(pytest_step)
    assert _index(job, "npm ci") <= _index(job, "vite build")
    assert '"$PLANNER_TEST_WORKSPACE"' in _runs(job)[_index(job, "df -T")]  # root of every test data folder
    for name in ("DATA_DIR", "PLANNER_TEST_WORKSPACE"):
        assert str(env[name]).startswith("${{ github.workspace }}/"), f"{name} must live under the workspace"
    assert env["HYPOTHESIS_PROFILE"] == "ci"

    command = pytest_step["run"]
    assert "$PENDING_FLAGS" in command
    assert '-m "not real_provider and not pi"' in command
    assert "--cov-fail-under=80" in command
    assert not pytest_step.get("continue-on-error")
    domain_gate = job["steps"][job["steps"].index(pytest_step) + 1]
    assert "--include='*/overland_planner/domain/*' --fail-under=90" in domain_gate["run"]
    assert not domain_gate.get("continue-on-error")


PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"
MAKEFILE = REPO_ROOT / "Makefile"


def test_walking_skeleton_is_blocking_in_test_python() -> None:
    """Slice 01a (D180): the walking skeleton runs in job 2's blocking pytest run, in pre-push and in `make test`."""
    workflow = _workflow()
    job = _job(workflow, "test-python")
    pytest_steps = [s for s in job["steps"] if "pytest" in s.get("run", "")]

    assert pytest_steps == [_main_pytest(job)], "the walking skeleton runs in the one blocking pytest step"
    assert "walking_skeleton" not in json.dumps(pytest_steps)
    non_blocking = [
        (name, step.get("name"))
        for name in COMMIT_STAGE
        for step in _job(workflow, name)["steps"]
        if step.get("continue-on-error")
    ]
    assert non_blocking == [], f"no commit-stage step may be non-blocking: {non_blocking}"

    hooks = {h["id"]: h for repo in yaml.safe_load(PRE_COMMIT.read_text())["repos"] for h in repo["hooks"]}
    pre_push = hooks["pytest-fast"]
    assert pre_push["stages"] == ["pre-push"]
    assert "walking_skeleton" not in pre_push["entry"], "pre-push runs the walking skeleton"
    assert "web/dist/index.html" in pre_push["entry"], "pre-push builds the web page the walking skeleton checks"
    fast = re.search(r"^PYTEST_FAST := (?P<selection>.*)$", MAKEFILE.read_text(), re.MULTILINE)
    assert fast is not None and "walking_skeleton" not in fast["selection"], "make test runs the walking skeleton"


LINT_GATES = (
    "uv lock --check",
    "ruff format --check",
    "ruff check",
    "mypy",
    "lint-imports",
    "gitleaks git",
    "hadolint Dockerfile",
    "actionlint",
    'shellcheck" --severity=info .github/scripts/*.sh deploy/scripts/*.sh',  # D89 deploy scripts (step 02-05)
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
    if uses.startswith("docker/login-action@"):
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
        }, f"{name} must log in and push on main"
        unguarded = [step.get("name", step.get("uses")) for step in writers if step.get("if") != MAIN_PUSH]
        assert unguarded == [], f"{name} writes to GHCR outside main pushes: {unguarded}"

        pushes = [b for b in builds if _writes_to_registry(b)]
        assert len(pushes) == 1, f"{name} pushes exactly once"
        push = pushes[0]
        assert f"name={IMAGE}" in push["with"]["outputs"] and "push-by-digest=true" in push["with"]["outputs"]
        assert push["with"]["sbom"] is True and "mode=max" in str(push["with"]["provenance"])
        assert any(f"type=gha,scope={scope}" in str(b["with"].get("cache-to", "")) for b in builds)

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


def test_arm64_smoke_checks_healthz_solver_and_data_folder_probes() -> None:
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
        "tour_solver file_store mount_table data_dir",
        '!= "ok"',
        "import ortools",
        "docker logs",
    ):
        assert fragment in script, f"image-smoke.sh lacks {fragment!r}"
    syntax = subprocess.run(["bash", "-n", str(IMAGE_SMOKE)], capture_output=True, text=True, check=False)
    assert syntax.returncode == 0, syntax.stderr


def test_image_jobs_have_job_level_package_permissions() -> None:
    workflow = _workflow()

    assert workflow["permissions"] == {"contents": "read"}, "write scopes live on the image and publish jobs (D161)"
    for name in REGISTRY_WRITERS:
        # D195: no GitHub attestations, so no id-token or attestations scope.
        assert _job(workflow, name)["permissions"] == {"contents": "read", "packages": "write"}, f"{name} permissions"
    # e2e deletes the image artifact it consumed (D169); that needs actions: write and nothing else.
    assert _job(workflow, "e2e")["permissions"] == {"contents": "read", "actions": "write"}
    for name, job in workflow["jobs"].items():
        if name not in (*REGISTRY_WRITERS, "e2e"):
            assert "permissions" not in job, f"{name} must inherit read-only permissions"


# ------------------------------------------------------------------------------------------- step 01-09: jobs 7-9
D160_PUBLISH_IF = (
    f"always() && !cancelled() && {MAIN_PUSH}"
    " && needs.image-amd64.result == 'success' && needs.image-arm64.result == 'success'"
    " && needs.e2e.result == 'success'"
    """ && contains(fromJSON('["success","skipped"]'), needs.mutation.result)"""
)


def _step_using(job: dict[str, Any], action: str) -> dict[str, Any]:
    steps = _uses(job, action)
    assert len(steps) == 1, f"expected exactly one {action} step"
    return steps[0]


def test_e2e_deletes_image_artifact_after_load() -> None:
    workflow = _workflow()
    job = _job(workflow, "e2e")
    amd64 = _job(workflow, "image-amd64")
    steps = job["steps"]

    assert _needs(job) == {"image-amd64"}, "e2e needs only the amd64 image (job 5)"
    download = _step_using(job, "actions/download-artifact")
    assert download["with"]["name"] == "planner-image-amd64"
    upload_id = _uses(amd64, "actions/upload-artifact")[0]["id"]
    assert amd64["outputs"]["artifact-id"] == f"${{{{ steps.{upload_id}.outputs.artifact-id }}}}"

    load, delete = _index(job, "docker load"), _index(job, "actions/artifacts/")
    assert steps.index(download) < load < delete, "the artifact is deleted only after the image is loaded"
    deletion = steps[delete]
    assert "-X DELETE" in deletion["run"] and "needs.image-amd64.outputs.artifact-id" in str(deletion["env"])

    playwright = _index(job, "playwright test")
    assert delete < playwright and _index(job, "playwright install") < playwright
    assert "chromium" in _runs(job)[_index(job, "playwright install")]
    assert "webkit" in _runs(job)[_index(job, "playwright install")]


COMPOSE_CI_STACK = "docker compose -f deploy/compose.yaml -f deploy/compose.ci.yaml"


def test_e2e_runs_on_the_compose_stack_and_tears_it_down_before_the_selection() -> None:
    job = _job(_workflow(), "e2e")
    steps = job["steps"]

    assert job["env"]["PLANNER_BIND"] == "127.0.0.1", "compose.yaml fails closed without PLANNER_BIND"
    assert all("docker run" not in script for script in _runs(job)), "job 7 starts the planner only through compose"
    up = _index(job, f"{COMPOSE_CI_STACK} up -d --wait")
    down = _index(job, f"{COMPOSE_CI_STACK} down -v")
    playwright = _index(job, "playwright test")
    assert _index(job, "docker load") < up < playwright < down < _index(job, "pytest-selection.sh")
    assert steps[down]["if"] == "always()"
    assert "--project=chromium --project=webkit-iphone14" in _runs(job)[playwright]


def test_e2e_runs_compose_or_security_selection_with_external_flag() -> None:
    job = _job(_workflow(), "e2e")
    selection = job["steps"][_index(job, "pytest-selection.sh")]

    assert "'compose or security'" in selection["run"] or '"compose or security"' in selection["run"]
    assert job["env"]["PLANNER_IMAGE"] == "overland-planner:ci-${{ github.sha }}", "the image loaded from job 5"
    assert not selection.get("continue-on-error"), "the packaged-planner password check blocks publish"
    script = PYTEST_SELECTION.read_text()
    assert "--run-external" in script and "$PENDING_FLAGS" in script


def test_e2e_checks_the_packaged_planner_without_data_storage_until_slice_01a_is_enabled() -> None:
    # Step 03-02: the @compose scenario runs on the loaded image with PLANNER_IMAGE; reported only until 03-10 enables
    # slice 01a in PENDING_FLAGS, after which the compose selection runs it as a blocking check.
    job = _job(_workflow(), "e2e")
    check = job["steps"][_index(job, "without_its_data_storage")]

    assert "--run-pending=slice-01a" in check["run"] and "--run-external" in check["run"]
    assert check.get("continue-on-error") is True
    assert _index(job, f"{COMPOSE_CI_STACK} down -v") < _index(job, "without_its_data_storage")


FAIL_CLOSED_COMPOSE_VARIABLES = ("PLANNER_IMAGE", "PLANNER_BIND")  # D174: compose.yaml interpolates both with :?


def test_every_compose_run_sets_the_fail_closed_variables_in_its_env() -> None:
    # Compose interpolates deploy/compose.yaml before any override file, so the variables must be in the step's
    # environment (workflow, job or step `env:`), not left to an override or an inline shell prefix.
    compose_runs = 0
    missing = []
    for path in (WORKFLOW, WEEKLY):
        workflow = yaml.safe_load(path.read_text())
        for name, job in workflow["jobs"].items():
            for step in job.get("steps", []):
                if "docker compose -f deploy/compose.yaml" not in step.get("run", ""):
                    continue
                compose_runs += 1
                env = workflow.get("env", {}) | job.get("env", {}) | step.get("env", {})
                gaps = [v for v in FAIL_CLOSED_COMPOSE_VARIABLES if not str(env.get(v, "")).strip()]
                if gaps:
                    missing.append(f"{path.name}:{name}:{step.get('name', step['run'][:40])} lacks {gaps}")

    assert compose_runs >= 6, "job 7 and the weekly compose-stack job each start, log and stop the stack"
    assert missing == []


def _fake_uv(tmp_path: Path, exit_code: int) -> dict[str, str]:
    fake = tmp_path / "bin" / "uv"
    fake.parent.mkdir()
    fake.write_text(f'#!/usr/bin/env bash\necho "fake pytest $*"\nexit {exit_code}\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return {**os.environ, "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}"}


@pytest.mark.parametrize(
    ("pending_flags", "pytest_exit", "expected_exit", "summary_fragment"),
    [
        ("", 5, 0, "empty by design"),  # no slice enabled yet: nothing to select is the expected state
        ("--run-pending=slice-00b", 5, 5, "selected no test"),  # an enabled slice must select something
        ("", 1, 1, "failed"),
        ("--run-pending=slice-00b", 0, 0, "passed"),
    ],
)
def test_empty_pytest_selection_passes_only_by_design(
    tmp_path: Path, pending_flags: str, pytest_exit: int, expected_exit: int, summary_fragment: str
) -> None:
    summary = tmp_path / "summary.md"
    env = {**_fake_uv(tmp_path, pytest_exit), "PENDING_FLAGS": pending_flags, "GITHUB_STEP_SUMMARY": str(summary)}

    run = subprocess.run(
        ["bash", str(PYTEST_SELECTION), "compose or security"], env=env, capture_output=True, text=True, check=False
    )

    assert run.returncode == expected_exit, run.stdout + run.stderr
    assert "--run-external" in run.stdout and "-m compose or security" in run.stdout
    assert summary_fragment in summary.read_text()


def test_mutation_job_runs_only_for_domain_or_application_changes() -> None:
    workflow = _workflow()
    job = _job(workflow, "mutation")
    changes = _job(workflow, "changes")
    filter_script = "\n".join(_runs(changes))

    assert _needs(job) == {"changes", "test-python"}, "mutation needs job 2"
    assert job["if"] == f"{MAIN_PUSH} && needs.changes.outputs.core == 'true'"
    assert changes["outputs"]["core"] == "${{ steps.filter.outputs.core }}"
    assert "^src/overland_planner/(domain|application)/" in filter_script
    assert job["timeout-minutes"] == 30
    assert _index(job, "vite build") < _index(job, "make mutate"), "mutmut copies web/dist (D162)"
    mutate = job["steps"][_index(job, "make mutate")]
    assert "BASE=" in mutate["run"] and "github.event.before" in str(mutate.get("env", {}))
    assert "0000000000000000000000000000000000000000" in mutate["run"], "new branch or forced push mutates all"
    assert "GITHUB_STEP_SUMMARY" in mutate["run"]
    dry = subprocess.run(
        ["make", "-n", "mutate", "BASE=all"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert "git ls-files -- src/overland_planner/domain src/overland_planner/application" in dry.stdout


def test_publish_gating_matches_d160() -> None:
    workflow = _workflow()
    job = _job(workflow, "publish")

    assert _needs(job) == {"image-amd64", "image-arm64", "e2e", "mutation"}
    assert job["if"] == D160_PUBLISH_IF
    assert _needs(_job(workflow, "mutation")) & {"image-amd64", "image-arm64", "e2e"} == set()


def test_no_job_uses_github_attestations() -> None:
    """D195: GitHub artifact attestations are unavailable for user-owned private repositories."""
    workflows = {path.name: yaml.safe_load(path.read_text()) for path in (WORKFLOW, WEEKLY)}

    for file, workflow in workflows.items():
        for scope in [workflow, *workflow["jobs"].values()]:
            granted = scope.get("permissions") or {}
            assert not {"id-token", "attestations"} & set(granted), f"{file}: {scope.get('name')} requests {granted}"
        for name, job in workflow["jobs"].items():
            for step in job.get("steps", []):
                text = f"{step.get('uses', '')} {step.get('run', '')}"
                assert "attest" not in text, f"{file}/{name} uses GitHub attestations: {text.strip()}"


def test_publish_creates_manifest_list_and_release_json() -> None:
    job = _job(_workflow(), "publish")
    create = _runs(job)[_index(job, "imagetools create")]

    assert "needs.image-amd64.outputs.digest" in str(job["steps"][_index(job, "imagetools create")]["env"])
    assert "needs.image-arm64.outputs.digest" in str(job["steps"][_index(job, "imagetools create")]["env"])
    assert ":sha-${GITHUB_SHA::12}" in create and ":main" in create

    release = _runs(job)[_index(job, "release.json")]
    for key in ("git_sha", "commit_ts", "digest", "alembic_head", "created", "provenance"):
        assert key in release, f"release.json lacks {key}"
    assert 'provenance: "buildx"' in release, "release.json records the D195 provenance source"
    assert "GITHUB_STEP_SUMMARY" in release
    upload = _step_using(job, "actions/upload-artifact")["with"]
    assert upload["name"] == "release.json"
    prune = _index(job, "ghcr_prune.py")
    assert (
        _index(job, "imagetools create") < prune
        and job["steps"].index(_step_using(job, "actions/upload-artifact")) < prune
    )


def test_publish_fails_closed_without_buildx_provenance_for_both_platforms() -> None:
    """D195: the manifest list must carry buildx provenance naming this repo and SHA before release.json exists."""
    job = _job(_workflow(), "publish")
    check = _index(job, "{{json .Provenance}}")
    step, script = job["steps"][check], _runs(job)[check]

    assert "imagetools inspect" in script and "steps.list.outputs.digest" in str(step.get("env", {}))
    assert "set -euo pipefail" in script, "a failed inspect or jq must fail the step"
    for fragment in ("linux/amd64", "linux/arm64", "GITHUB_SHA", "GITHUB_REPOSITORY", "GITHUB_STEP_SUMMARY", "exit 1"):
        assert fragment in script, f"provenance check lacks {fragment!r}"
    assert not step.get("continue-on-error")
    upload = job["steps"].index(_step_using(job, "actions/upload-artifact"))
    assert _index(job, "imagetools create") < check < _index(job, "release.json") < upload


def _prune_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ghcr_prune", GHCR_PRUNE)
    assert spec and spec.loader, "ghcr_prune.py missing"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"
digests = st.text("0123456789abcdef", min_size=8, max_size=8).map(lambda h: f"sha256:{h}")


@given(arches=st.lists(digests, min_size=1, max_size=3, unique=True), others=st.lists(digests, max_size=6))
def test_prune_deletes_only_versions_outside_the_release(arches: list[str], others: list[str]) -> None:
    """D195: buildx SBOM/provenance manifests hang off each per-arch index the list references; they must survive."""
    release, referrer = "sha256:release0", "sha256:referrer"
    images = {arch: f"{arch}-image" for arch in arches}
    provenance = {arch: f"{arch}-attest" for arch in arches}
    belongs = {release, referrer, *arches, *images.values(), *provenance.values()}
    stale = [d for d in dict.fromkeys(others) if d not in belongs]
    manifests: dict[str, dict[str, Any]] = {
        release: {"mediaType": INDEX, "manifests": [{"digest": a, "mediaType": INDEX} for a in arches]},
        **{
            a: {
                "mediaType": INDEX,
                "manifests": [
                    {"digest": images[a], "mediaType": MANIFEST},
                    {
                        "digest": provenance[a],
                        "mediaType": MANIFEST,
                        "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
                    },
                ],
            }
            for a in arches
        },
        referrer: {"mediaType": MANIFEST, "subject": {"digest": release}},  # any OCI referrer of the list
        **{d: {"mediaType": MANIFEST} for d in (*images.values(), *provenance.values(), *stale)},
    }
    versions = [
        {"id": n, "name": d, "metadata": {"container": {"tags": ["main", "sha-0123456789ab"] if d == release else []}}}
        for n, d in enumerate([release, referrer, *arches, *images.values(), *provenance.values(), *stale])
    ]

    plan = _prune_module().decide(versions, release, manifests.get)

    assert plan.skip_reason is None
    assert sorted(v["name"] for v in plan.delete) == sorted(stale)
    assert belongs <= plan.keep


@pytest.mark.parametrize("ambiguity", ["release not listed", "manifest unreadable", "main tag elsewhere"])
def test_prune_skips_everything_when_ambiguous(ambiguity: str) -> None:
    release, child, old = "sha256:release0", "sha256:child000", "sha256:old00000"
    manifests: dict[str, dict[str, Any]] = {
        release: {"mediaType": INDEX, "manifests": [{"digest": child, "mediaType": MANIFEST}]},
        child: {"mediaType": MANIFEST},
        old: {"mediaType": MANIFEST},
    }
    tags = {release: ["main"], child: [], old: []}
    if ambiguity == "manifest unreadable":
        del manifests[old]
    if ambiguity == "main tag elsewhere":
        tags[old] = ["main"]
    listed = [child, old] if ambiguity == "release not listed" else [release, child, old]
    versions = [{"id": n, "name": d, "metadata": {"container": {"tags": tags[d]}}} for n, d in enumerate(listed)]

    plan = _prune_module().decide(versions, release, manifests.get)

    assert plan.delete == [] and plan.skip_reason


def test_weekly_workflow_rescans_audits_and_reports_without_gating_deploys() -> None:
    assert WEEKLY.is_file(), ".github/workflows/weekly.yml missing"
    text = WEEKLY.read_text()
    weekly = yaml.safe_load(text)
    triggers = _triggers(weekly)

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"] == [{"cron": "0 5 * * 1"}], "Monday 05:00 UTC"
    assert weekly["permissions"] == {"contents": "read"}
    scripts = "\n".join(s for job in weekly["jobs"].values() for s in _runs(job))
    for fragment in (
        "trivy image",
        ":main",
        "pip-audit",
        "npm audit --omit=dev",
        "packages/container/overland-planner/versions",
        "GITHUB_STEP_SUMMARY",
    ):
        assert fragment in scripts, f"weekly.yml lacks {fragment!r}"
    deep = [job for job in weekly["jobs"].values() if job.get("env", {}).get("HYPOTHESIS_PROFILE") == "deep"]
    stack = [job for job in weekly["jobs"].values() if any("deploy/compose.yaml up -d --wait" in s for s in _runs(job))]
    assert len(stack) == 1, "one weekly job runs main on the compose stack"
    assert stack[0]["env"]["PLANNER_IMAGE"] == f"{weekly['env']['IMAGE']}:main", "the stack runs the pulled main"
    zap = [s for s in stack[0]["steps"] if "zap-baseline.py" in s.get("run", "")]
    assert len(zap) == 1 and zap[0]["continue-on-error"] is True, "the ZAP baseline never blocks"
    assert re.search(r"ZAP_IMAGE: \S+@sha256:[0-9a-f]{64}", text), "ZAP image pinned by digest"
    assert any("--project=firefox --project=webkit-desktop" in s for s in _runs(stack[0]))
    assert len(deep) == 1, "one job runs the deep property profile"
    assert "workflow_run" not in _triggers(_workflow()), "ci.yml (and so publish) never waits for the weekly run"
    refs = [(m["ref"], m["comment"]) for m in USES.finditer(text)]
    assert [r for r, c in refs if not (PINNED.match(r) and TAG_COMMENT.search(c))] == []


STEP_FILE_APPEND = re.compile(r'>>\s*"?\$\{?(?P<target>GITHUB_OUTPUT|GITHUB_STEP_SUMMARY)\b')


def test_run_blocks_group_step_file_appends_for_shellcheck() -> None:
    """SC2129 offline guard: actionlint+shellcheck in job 1 lint rejects repeated `>> file` in one script."""
    repeated = []
    for path in (WORKFLOW, WEEKLY):
        for job_name, job in yaml.safe_load(path.read_text())["jobs"].items():
            for script in _runs(job):
                targets = [m["target"] for m in STEP_FILE_APPEND.finditer(script)]
                repeated += [f"{path.name}:{job_name} -> {t}" for t in set(targets) if targets.count(t) > 1]
    assert repeated == [], 'group appends as `{ ...; } >> "$FILE"` (SC2129)'


def test_image_metadata_and_release_json_carry_the_alembic_head_of_the_repository(tmp_path: Path) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini"))).get_current_head()
    workflow = _workflow()
    for name in IMAGE_JOBS:
        meta = next(step for step in _job(workflow, name)["steps"] if step.get("id") == "meta")
        output = tmp_path / f"{name}.out"
        result = subprocess.run(
            ["bash", "-e", "-c", meta["run"]],
            cwd=REPO_ROOT,
            env={**os.environ, "GITHUB_OUTPUT": str(output)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert f"alembic_head={head}" in output.read_text().splitlines(), f"{name} labels the wrong Alembic head"
    release = _runs(_job(workflow, "publish"))[_index(_job(workflow, "publish"), "release.json")]
    assert '--arg alembic_head "$alembic_head"' in release and 'pathlib.Path("migrations/versions")' in release


SHELLCHECK_RELEASE = "0.11.0"  # shellcheck-py 0.11.0.1 in the Makefile (make lint-ci) and .pre-commit-config.yaml


def test_lint_uses_the_pinned_shellcheck_never_the_runner_one() -> None:
    """Step 02-07: the runner's preinstalled shellcheck once disagreed with make lint-ci (SC2015 at info)."""
    job = _job(_workflow(), "lint")
    install = job["steps"][_index(job, "shellcheck.tar.xz")]
    runs = _runs(job)
    shellcheck_runs = [line.strip() for run in runs for line in run.splitlines() if re.search(r"shellcheck\b", line)]
    makefile = (REPO_ROOT / "Makefile").read_text()
    pre_commit = (REPO_ROOT / ".pre-commit-config.yaml").read_text()

    assert install["env"]["SHELLCHECK_VERSION"] == SHELLCHECK_RELEASE
    assert re.fullmatch(r"[0-9a-f]{64}", install["env"]["SHELLCHECK_SHA256"])
    assert "sha256sum --check --strict" in install["run"]
    assert _index(job, "shellcheck.tar.xz") < _index(job, 'actionlint" -color')
    assert '-shellcheck "$RUNNER_TEMP/shellcheck"' in runs[_index(job, 'actionlint" -color')]
    bare = [line for line in shellcheck_runs if re.match(r"shellcheck\b", line)]
    assert bare == [], f"lint runs the runner's shellcheck from PATH: {bare}"
    assert '"$RUNNER_TEMP/shellcheck" --severity=info .github/scripts/*.sh deploy/scripts/*.sh' in "\n".join(runs)
    assert f"SHELLCHECK_PY := shellcheck-py=={SHELLCHECK_RELEASE}.1" in makefile
    assert "SHELLCHECK_SEVERITY := info" in makefile and "--severity=$(SHELLCHECK_SEVERITY)" in makefile
    assert f"rev: v{SHELLCHECK_RELEASE}.1" in pre_commit and "args: [--severity=info]" in pre_commit


def test_job_7_selection_runs_the_enabled_slice_00b_security_checks() -> None:
    """D170: with slice 00b enabled the compose/security selection must collect the packaged-planner checks."""
    expression = "compose or security"
    assert f'pytest-selection.sh "{expression}"' in _runs(_job(_workflow(), "e2e"))[-1]
    pending = _workflow()["env"]["PENDING_FLAGS"].split()

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "--run-external", *pending, "-m", expression],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert "test_slice_00b.py::test_sharing_the_packaged_planner_never_shares_marcos_password" in collected.stdout
    assert "test_container_hardening.py::test_planner_container_writes_only_data_and_tmp_without_privileges" in (
        collected.stdout
    )

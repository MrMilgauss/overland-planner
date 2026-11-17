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
    "slow-properties": RUNNER,
    "slow-a6": RUNNER,
    "golden-order": RUNNER,
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

    # D170: slice 00b is GREEN (step 02-07), slice 01a (step 03-10), slice 01b (step 04-11), slice 02 (step 05-12),
    # slice 03 (step 06-13), slice 03b (step 07-13), slice 06a (step 09-11).
    assert workflow["env"]["PENDING_FLAGS"] == (
        "--run-pending=slice-00b --run-pending=slice-01a --run-pending=slice-01b --run-pending=slice-02"
        " --run-pending=slice-03 --run-pending=slice-03b --run-pending=slice-06a"
    )
    assert _index(job, "vite build") < _index(job, "df -T") < job["steps"].index(pytest_step)
    assert _index(job, "npm ci") <= _index(job, "vite build")
    assert '"$PLANNER_TEST_WORKSPACE"' in _runs(job)[_index(job, "df -T")]  # root of every test data folder
    for name in ("DATA_DIR", "PLANNER_TEST_WORKSPACE"):
        assert str(env[name]).startswith("${{ github.workspace }}/"), f"{name} must live under the workspace"
    assert env["HYPOTHESIS_PROFILE"] == "ci"

    command = pytest_step["run"]
    assert "$PENDING_FLAGS" in command
    # A-6 (step 05-12) and the three slice-02 HC properties (D221) run in slow-properties, the golden order in job 3.
    assert '-m "not real_provider and not pi and not slow and not heavy_property and not golden_order"' in command
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
    " && needs.slow-properties.result == 'success'"  # D220 h: the slow properties gate publish (step 05-12)
    " && needs.slow-a6.result == 'success'"  # D231: the A-6 property has its own job and still gates publish
    " && needs.golden-order.result == 'success'"  # job 3: a different golden order never publishes (step 06-02)
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


def test_every_e2e_step_blocks_once_slice_01a_is_enabled() -> None:
    # Step 03-10 (D170): slice 01a is in PENDING_FLAGS, so the 03-02 non-blocking run of the @compose scenario is gone;
    # the compose/security selection runs it as a blocking check (test_job_7_selection_runs_the_enabled_slices...).
    job = _job(_workflow(), "e2e")

    assert [s.get("name") for s in job["steps"] if s.get("continue-on-error")] == []
    assert all("without_its_data_storage" not in script for script in _runs(job))


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


def test_mutation_job_runs_only_when_asked_for_on_manual_dispatch() -> None:
    """D238: job 8 cannot finish (D224); a push never selects it, `workflow_dispatch` with mutation=true does."""
    workflow = _workflow()
    job = _job(workflow, "mutation")
    dispatch = _triggers(workflow)["workflow_dispatch"]

    assert dispatch["inputs"]["mutation"]["type"] == "boolean"
    assert dispatch["inputs"]["mutation"]["default"] is False
    assert _needs(job) == {"test-python"}, "mutation needs job 2 and no longer the changes filter"
    assert job["if"] == "github.event_name == 'workflow_dispatch' && inputs.mutation"
    assert "needs.changes.outputs.core" not in job["if"]
    assert "push" not in job["if"], "a main push with a domain file no longer selects job 8"
    assert job["timeout-minutes"] == 75  # D213
    assert _index(job, "vite build") < _index(job, "make mutate"), "mutmut copies web/dist (D162)"
    mutate = job["steps"][_index(job, "make mutate")]
    assert "BASE=" in mutate["run"] and "github.event.before" in str(mutate.get("env", {}))
    assert "0000000000000000000000000000000000000000" in mutate["run"], "new branch or forced push mutates all"
    assert "GITHUB_STEP_SUMMARY" in mutate["run"]
    assert mutate["run"].splitlines()[0] == "set -o pipefail", "`make mutate | tee` must keep make's exit code"
    dry = subprocess.run(
        ["make", "-n", "mutate", "BASE=all"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert "git ls-files -- src/overland_planner/domain src/overland_planner/application" in dry.stdout


def test_publish_gating_matches_d160() -> None:
    workflow = _workflow()
    job = _job(workflow, "publish")

    assert _needs(job) == {
        "image-amd64",
        "image-arm64",
        "e2e",
        "slow-properties",
        "slow-a6",
        "golden-order",
        "mutation",
    }
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


def test_publish_runs_the_make_deploy_gate_so_each_statement_subject_is_its_platform_image() -> None:
    """F10: the in-toto subject of each platform's provenance must be that platform's image manifest, checked by the
    same deploy/scripts/verify_provenance.py the Mac runs, before release.json exists."""
    job = _job(_workflow(), "publish")
    gate = _index(job, "deploy/scripts/verify_provenance.py")
    step, script = job["steps"][gate], _runs(job)[gate]

    assert '--sha "$GITHUB_SHA"' in script and "steps.list.outputs.digest" in str(step.get("env", {}))
    assert "secrets.GITHUB_TOKEN" in str(step["env"].get("GH_TOKEN")) and not step.get("continue-on-error")
    assert _index(job, "{{json .Provenance}}") < gate < _index(job, "release.json")


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


def test_job_7_selection_runs_the_enabled_slices_compose_and_security_checks() -> None:
    """D170: with slices 00b and 01a enabled the compose/security selection must collect the packaged-planner checks."""
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
    assert (
        "test_slice_01a.py::test_the_packaged_planner_started_without_its_data_storage_reports_that_projects_would_be_lost"
        in collected.stdout
    )
    assert "test_container_hardening.py::test_planner_container_writes_only_data_and_tmp_without_privileges" in (
        collected.stdout
    )


FEATURE_01B = "tests/acceptance/overland_route_planner_mvp/slice-01b-skeleton-plan-and-gpx.feature"
MODULE_01B = "tests/acceptance/overland_route_planner_mvp/test_slice_01b.py"


def _collect(*selection: str, module: str = MODULE_01B) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider", *selection, module],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_slice_01b_scenarios_run_without_being_enabled() -> None:
    """Step 04-11: the feature-level tags are what conftest reads to skip a slice; `@pending` must be gone from them."""
    lines = (REPO_ROOT / FEATURE_01B).read_text().splitlines()

    assert [line for line in lines if line.startswith("@")] == ["@slice-01b"]


def test_job_2_installs_chromium_after_npm_ci_and_before_pytest() -> None:
    """D170: without the browser the @ui scenario would fail in job 2; the package alone comes from npm ci."""
    job = _job(_workflow(), "test-python")
    install = _index(job, "playwright install")
    step = job["steps"][install]

    assert _index(job, "npm ci") < install < job["steps"].index(_main_pytest(job))
    assert step["run"] == "npx --no-install playwright install --with-deps chromium"
    assert step["working-directory"] == "web"
    assert not step.get("continue-on-error")


def test_job_2_selection_includes_the_browser_scenario() -> None:
    """Job 2, not job 7: only job 2 has the web/dist the scenario's real server serves."""
    command = _main_pytest(_job(_workflow(), "test-python"))["run"]
    expression = re.search(r'-m "(?P<expression>[^"]+)"', command)
    assert expression is not None

    collected = _collect("-m", expression["expression"])

    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert "test_marco_plans_the_assietta_day_trip_in_his_browser" in collected.stdout


def test_pre_push_selects_no_slice_01b_scenario() -> None:
    """D199: pre-push stays under five minutes; the 01b scenarios are real solves and a browser."""
    hooks = {h["id"]: h for repo in yaml.safe_load(PRE_COMMIT.read_text())["repos"] for h in repo["hooks"]}
    expression = re.search(r'-m "(?P<expression>[^"]+)"', hooks["pytest-fast"]["entry"])
    assert expression is not None

    collected = _collect("-m", expression["expression"])

    assert collected.returncode == 5, collected.stdout + collected.stderr  # pytest: nothing selected
    assert "deselected" in collected.stdout, "the module must have collected scenarios to deselect"


def test_weekly_deep_properties_selects_the_solves_but_not_the_browser_scenario() -> None:
    """The job installs no browser, so the @ui scenario would fail in it; job 2 is where that scenario runs."""
    job = yaml.safe_load(WEEKLY.read_text())["jobs"]["deep-properties"]
    expression = re.search(r'-m "(?P<expression>[^"]+)"', _runs(job)[_index(job, "pytest")])
    assert expression is not None

    collected = _collect("-m", expression["expression"])

    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert "test_marco_plans_the_assietta_day_trip_in_his_browser" not in collected.stdout
    assert "test_marco_gets_a_first_ordered_itinerary" in collected.stdout
    assert not any("playwright install" in script for script in _runs(job)), "with a browser, select the scenario again"


# ------------------------------------------------------------------------- step 05-12: slice 02 blocking in CI
FEATURE_02 = "tests/acceptance/overland_route_planner_mvp/slice-02-directional-optimizer.feature"
MODULE_02 = "tests/acceptance/overland_route_planner_mvp/test_slice_02.py"
A_6 = "test_any_project_planned_twice_from_scratch_gets_the_same_plan"
IDENTICAL_INPUTS = "test_identical_inputs_produce_identical_plans"
SLICE_02_PROPERTIES = (
    "test_no_generated_plan_ever_drives_a_track_in_reverse",  # HC-1
    "test_tracks_are_always_driven_in_full",  # HC-5
    "test_the_trip_always_starts_at_start_and_ends_at_end",  # A-2
)


def _collected_slice_02(expression: str) -> list[str]:
    pending = _workflow()["env"]["PENDING_FLAGS"].split()
    collected = _collect(*pending, "-m", expression, module=MODULE_02)
    assert collected.returncode in (0, 5), collected.stdout + collected.stderr
    return [line.split("::", 1)[1] for line in collected.stdout.splitlines() if line.startswith(f"{MODULE_02}::")]


def test_slice_02_scenarios_run_without_being_enabled() -> None:
    """Step 05-12: the feature-level tags are what conftest reads to skip a slice; `@pending` must be gone from them."""
    lines = (REPO_ROOT / FEATURE_02).read_text().splitlines()

    assert [line for line in lines if line.startswith("@")] == ["@slice-02"]


def _collected_node_ids(expression: str) -> list[str]:
    """Node ids the expression selects in the whole suite, as the slow-properties job runs it (no module)."""
    pending = _workflow()["env"]["PENDING_FLAGS"].split()
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider", *pending, "-m", expression],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert collected.returncode in (0, 5), collected.stdout + collected.stderr
    return sorted(line for line in collected.stdout.splitlines() if "::" in line)


def _names(node_ids: list[str]) -> list[str]:
    return sorted(node_id.rsplit("::", 1)[1] for node_id in node_ids)


def _collected_everywhere(expression: str) -> list[str]:
    """Test names the expression selects in the whole suite, as the slow-properties job runs it (no module)."""
    return _names(_collected_node_ids(expression))


# ---------------------------------------------------------------- step 06-12: CI placement of the slice 03 scenarios
MODULE_03 = "tests/acceptance/overland_route_planner_mvp/test_slice_03.py"
SLOW_SLICE_03 = (
    "test_the_best_plan_is_returned_at_the_optimisation_limit",  # #2, waits out the 20 s optimisation limit
    "test_no_valid_route_within_the_feasibility_limit",  # #10, waits out the 30 s feasibility limit
    "test_the_feasibility_limit_during_the_road_look_up",  # #13, waits out the 30 s feasibility limit
)
GOLDEN_SCENARIO = "test_the_sixty_item_plan_is_the_same_on_every_machine"  # #6, I1 at the default budget
PI_SCENARIOS = (  # #1 and #3: make perf-pi only (D96)
    "test_the_solve_stage_for_60_items_fits_the_budget_on_the_pi",
    "test_a_plan_found_on_the_pi_is_nearly_as_good_as_a_long_search",
)
HEAVY_REGISTRY_PROPERTIES = (  # the five at about 5 s or more each at profile ci on the Mac (06-12)
    "test_any_presses_and_endings_keep_one_job_per_project_and_one_in_the_solver",
    "test_another_project_waits_for_the_solver_slot",
    "test_the_active_job_check_comes_after_the_anchors_and_before_the_optimizer",
    "test_two_fast_presses_start_one_job",
    "test_a_job_waiting_for_the_optimizer_gives_up_at_the_feasibility_limit_counted_from_its_start",
)

HEAVY_UNIT_AND_PERF = {  # >= 3 s each at profile ci on the Mac when job 2 hit its timeout (run 42840993896)
    "tests/unit/application/planning/test_plan_job_registry.py": (
        "test_calculate_reports_the_ignore_memo_it_was_given_and_refuses_alike_with_or_without_it",
        "test_whatever_the_work_raises_the_job_ends_failed_and_calculate_is_accepted_again",
        "test_a_job_row_holds_the_values_of_its_finished_line_with_its_start_and_end",
        "test_a_failed_job_logs_its_end_at_warning_and_a_done_job_at_info",
        "test_a_job_logs_one_finished_event_and_a_stored_run_one_completed_event",
        "test_any_solver_outcome_ends_in_one_terminal_state_with_a_run_named_iff_one_was_stored",
        "test_the_project_stays_readable_while_the_optimizer_works",
        "test_the_request_answers_before_the_job_is_done_and_no_run_is_named_until_stored",
        "test_a_finished_job_is_kept_for_ten_minutes_and_a_running_one_as_long_as_it_runs",
    ),
    "tests/unit/adapters/http/test_basic_auth_credentials.py": (
        "test_a_change_is_made_only_with_the_configured_user_and_exact_password",
    ),
    "tests/perf/test_golden_instances.py": (
        "test_every_instance_keeps_its_shape",
        "test_the_sparse_road_map_turns_about_five_percent_of_its_own_pairs_into_one_way_detours",
    ),
    "tests/unit/application/export/test_gpx_export_service.py": (
        "test_failed_run_export_is_refused_with_422_and_its_message",
        "test_the_file_and_the_document_are_named_from_the_project_and_the_run",
        "test_inconsistent_file_logs_invariant_violation",
        "test_each_export_logs_one_event_with_the_kpi_fields",
        "test_inconsistent_file_refuses_with_the_verbatim_message",
        "test_export_changes_nothing_and_unknown_run_is_not_found",
        "test_the_document_holds_every_track_with_its_name_and_its_stored_points_in_order",
        "test_a_retraced_run_exports_each_track_forwards_and_its_retrace_as_its_own_marked_leg",
        "test_a_retrace_that_does_not_match_its_recorded_hash_refuses_the_file",
    ),
    "tests/unit/application/planning/test_plan_request_job_guard.py": (
        "test_a_track_of_real_size_passes_and_one_altered_point_anywhere_fails",
        "test_a_ready_run_stores_and_shows_each_stop_with_its_columns_and_a_failed_run_no_stops",
        "test_a_failed_run_stores_and_shows_its_reason_in_product_words_and_a_ready_run_no_report",
        "test_a_track_whose_file_changed_or_vanished_stores_one_failed_run_and_no_itinerary",
        "test_a_ready_run_stores_and_shows_the_totals_of_its_stops_and_a_failed_run_none",
        "test_a_passing_plan_is_stored_ready_and_logged_with_invariants_ok",
        "test_a_retraced_plan_is_stored_with_the_reversed_points_hash_and_a_damaged_retraced_track_fails_it",
    ),
    "tests/perf/test_reference_search.py": (
        "test_a_short_search_writes_a_complete_reference_better_than_the_listed_order",
    ),
    "tests/unit/domain/planning/test_invariant_guard.py": (
        "test_any_single_mutation_of_a_passing_plan_fails_and_names_its_rule",
        "test_a_chosen_order_breaking_an_anchor_or_an_item_fails_naming_its_rule",
        "test_any_single_retrace_perturbation_fails_and_names_its_rule",
        "test_any_single_leg_level_reason_or_offroad_time_perturbation_fails_and_names_its_rule",
        "test_a_chosen_order_with_a_pair_no_road_or_retrace_joins_fails_naming_both_items",
    ),
    "tests/unit/bootstrap/test_settings.py": (
        "test_valid_settings_parse_to_their_values_and_unrelated_keys_are_ignored",
        "test_an_empty_upload_cap_falls_back_to_its_default",
    ),
    "tests/unit/application/planning/test_plan_request_job_outcomes.py": (
        "test_how_the_solve_ended_gives_one_run_with_its_flags_and_the_incumbents_show_while_solving",
        "test_the_incumbent_the_line_and_the_row_show_the_plans_road_metres_and_counts_not_the_solvers_cost",
        # 07-12: about 3 s each at profile ci on the Mac
        "test_an_incumbent_naming_no_tour_shows_as_streamed_and_a_solve_that_raises_still_counts_its_incumbents",
        "test_the_second_pass_asks_the_retrace_pair_only_where_the_first_pair_has_no_road_and_the_counters_add_up",
        "test_an_item_no_order_can_connect_fails_the_run_naming_it_before_the_solver_is_asked",
    ),
    "tests/unit/application/routing/test_leg_resolver.py": (
        "test_the_legs_found_are_kept_per_road_map_and_only_the_missing_ones_are_asked_after_the_held_ones_are_reported",
        "test_a_job_whose_road_map_answers_a_row_of_the_wrong_shape_ends_failed_with_no_run",
        "test_a_scripted_road_map_answers_its_script_on_listed_pairs_and_the_default_elsewhere",
    ),
    "tests/unit/application/planning/test_plan_job_stage_timings.py": (
        "test_an_ended_job_reports_each_stage_in_whole_ms_within_its_elapsed_time_and_a_memo_hit_no_solve",
        "test_a_running_job_shows_its_finished_stages_and_its_legs_and_items_once_known",
    ),
    "tests/unit/domain/planning/test_fingerprint.py": (
        "test_changing_any_single_solver_input_gives_another_fingerprint",
        "test_rebuilding_the_same_inputs_or_changing_only_what_totals_use_keeps_the_fingerprint",
    ),
    "tests/unit/domain/planning/test_plan_run_assembler.py": (
        "test_a_failed_run_reports_its_reason_in_product_words_and_a_ready_run_has_no_report",
        "test_cumulative_km_and_time_run_to_the_end_of_each_stop",
    ),
}


FEATURE_03 = "tests/acceptance/overland_route_planner_mvp/slice-03-pi-performance.feature"


def test_slice_03_scenarios_run_without_being_enabled() -> None:
    """Step 06-13: the feature-level tags are what conftest reads to skip a slice; `@pending` must be gone from them."""
    lines = (REPO_ROOT / FEATURE_03).read_text().splitlines()

    assert [line for line in lines if line.startswith("@")] == ["@slice-03"]


FEATURE_03B = "tests/acceptance/overland_route_planner_mvp/slice-03b-out-and-back-retrace.feature"
MODULE_03B = "tests/acceptance/overland_route_planner_mvp/test_slice_03b.py"
HEAVY_SLICE_03B = ("test_no_track_item_is_ever_driven_backwards",)  # about 9 s at profile ci on the Mac (07-10, 07-13)


# bypass: one tag line, one observable outcome; no input space to generate over
def test_slice_03b_scenarios_run_without_being_enabled() -> None:
    """Step 07-13: the feature-level tags are what conftest reads to skip a slice; `@pending` must be gone from them."""
    lines = (REPO_ROOT / FEATURE_03B).read_text().splitlines()

    assert [line for line in lines if line.startswith("@")] == ["@slice-03b"]


FEATURE_06A = "tests/acceptance/overland_route_planner_mvp/slice-06a-valhalla-on-the-pi.feature"
CONTRACT_FEATURE = "tests/contract/routing_port/routing-engine-contract.feature"
MODULE_06A = "tests/acceptance/overland_route_planner_mvp/test_slice_06a.py"
MODULE_CONTRACT = "tests/contract/routing_port/test_routing_engine_contract.py"
LIVE_06A = (
    "test_marco_plans_with_valhalla_on_his_pi",
    "test_a_trail_entry_reached_by_a_forest_track_is_confirmed",
    "test_a_60_item_trip_with_no_known_roads_is_on_screen_within_3_minutes",
)
LIVE_CONTRACT = "test_the_routing_engine_on_the_pi_still_answers_like_its_recordings"


# bypass: tag lines and a flag list; no input space to generate over
def test_slice_06a_is_enabled_in_ci_and_its_files_say_so() -> None:
    """Step 09-11: the feature's tag line loses `@pending`, so do the contract scenarios of slice 06a (the slice 06b
    ones keep it), the pending-slices module no longer binds the feature, and PENDING_FLAGS enables the slice."""
    contract = (REPO_ROOT / CONTRACT_FEATURE).read_text().splitlines()
    still_pending = [line for line in contract if line.strip().startswith("@pending")]
    pending_slices = (REPO_ROOT / "tests/acceptance/overland_route_planner_mvp/test_pending_slices.py").read_text()

    assert [line for line in (REPO_ROOT / FEATURE_06A).read_text().splitlines() if line.startswith("@")] == [
        "@slice-06a"
    ]
    assert still_pending and all("@slice-06b" in line for line in still_pending)
    assert "slice-06a" not in pending_slices
    assert "--run-pending=slice-06a" in _workflow()["env"]["PENDING_FLAGS"].split()


def test_job_2_runs_the_slice_06a_scenarios_that_need_no_live_engine_and_leaves_the_live_ones_out() -> None:
    """Step 09-11: without any --run-pending flag, job 2's selection holds the 10 offline tests of the feature (the
    password outline counts three) and the 8 offline contract scenarios, and none of the live scenarios."""
    expression = re.search(r'-m "(?P<expression>[^"]+)"', _main_pytest(_job(_workflow(), "test-python"))["run"])
    assert expression is not None

    feature = _collect("-m", expression["expression"], module=MODULE_06A)
    contract = _collect("-m", expression["expression"], module=MODULE_CONTRACT)
    in_feature = {line.split("::", 1)[1] for line in feature.stdout.splitlines() if line.startswith(MODULE_06A)}
    in_contract = {line.split("::", 1)[1] for line in contract.stdout.splitlines() if line.startswith(MODULE_CONTRACT)}

    assert len(in_feature) == 10 and not in_feature & set(LIVE_06A)
    assert LIVE_CONTRACT not in in_contract


def _collected_slice_03(*selection: str) -> list[str]:
    pending = _workflow()["env"]["PENDING_FLAGS"].split()
    collected = _collect(*pending, *selection, module=MODULE_03)
    assert collected.returncode in (0, 5), collected.stdout + collected.stderr
    return sorted(line.split("::", 1)[1] for line in collected.stdout.splitlines() if line.startswith(f"{MODULE_03}::"))


def test_slow_properties_job_runs_the_slow_and_heavy_scenarios_at_profile_ci_and_job_2_does_not() -> None:
    """D220, D221, D223: A-6, the HC properties, the slice-03 scenarios that wait out a 20 s or 30 s limit, the
    costliest registry properties and the unit and perf tests at 3 s or more at profile ci; job 2 runs the rest of
    slice 03 but the @pi pair and the golden."""
    workflow = _workflow()
    job = _job(workflow, "slow-properties")
    pytest_steps = [s for s in job["steps"] if "pytest" in s.get("run", "")]
    job_2 = re.search(r'-m "(?P<expression>[^"]+)"', _main_pytest(_job(workflow, "test-python"))["run"])
    assert job_2 is not None

    assert job["name"] == "10 slow-properties"
    assert _needs(job) == {"changes"} and job["if"] == "needs.changes.outputs.code == 'true'"
    assert job["timeout-minutes"] == 40
    assert job["env"]["HYPOTHESIS_PROFILE"] == "ci"
    for name in ("DATA_DIR", "PLANNER_TEST_WORKSPACE"):
        assert job["env"][name] == _job(workflow, "test-python")["env"][name]
    assert _uses(job, "astral-sh/setup-uv") and "uv sync --frozen" in _runs(job)
    assert len(pytest_steps) == 1 and not pytest_steps[0].get("continue-on-error")
    assert _index(job, "df -T") < job["steps"].index(pytest_steps[0]), "D168: the data folder's filesystem is shown"
    assert '"$PLANNER_TEST_WORKSPACE"' in _runs(job)[_index(job, "df -T")]
    assert "GITHUB_STEP_SUMMARY" in _runs(job)[_index(job, "df -T")]
    command = pytest_steps[0]["run"]
    assert 'uv run pytest -q $PENDING_FLAGS -m "(slow or heavy_property) and not A_6"' in command  # empty exits 5
    assert "D221" in pytest_steps[0]["name"]
    expression = re.search(r'-m "(?P<expression>[^"]+)"', command)
    assert expression is not None

    moved = {f"{module}::{name}" for module, names in HEAVY_UNIT_AND_PERF.items() for name in names}
    slow = {*SLICE_02_PROPERTIES, *SLOW_SLICE_03, *HEAVY_REGISTRY_PROPERTIES, *HEAVY_SLICE_03B, *_names(sorted(moved))}
    job_10_ids = _collected_node_ids(expression["expression"])
    assert _names(job_10_ids) == sorted(slow)
    assert moved <= set(job_10_ids), "each moved unit or perf test is found under its own module"
    assert set(_collected_everywhere(job_2["expression"])).isdisjoint({A_6, *slow})
    others = set(_collected_slice_03()) - {*SLOW_SLICE_03, GOLDEN_SCENARIO, *PI_SCENARIOS}
    assert _collected_slice_03("-m", job_2["expression"]) == sorted(others)
    slice_03b = _collect(*workflow["env"]["PENDING_FLAGS"].split(), "-m", job_2["expression"], module=MODULE_03B)
    assert slice_03b.stdout.count(f"{MODULE_03B}::") == 6, "job 2 blocks on the six example scenarios of slice 03b"


def test_slow_a6_job_runs_the_a6_property_alone_at_profile_ci_in_parallel_with_job_10() -> None:
    """D231: A-6 (about 9.5 min on the Mac, about 20 min on a runner) split out of slow-properties, which took 34.4 min
    of its 40-minute timeout once; both jobs run in parallel and both gate publish."""
    workflow = _workflow()
    job = _job(workflow, "slow-a6")
    sibling = _job(workflow, "slow-properties")
    pytest_steps = [s for s in job["steps"] if "pytest" in s.get("run", "")]

    assert job["name"] == "11 slow-a6"
    assert _needs(job) == {"changes"} == _needs(sibling) and job["if"] == sibling["if"]
    assert job["timeout-minutes"] == 40
    assert job["env"] == sibling["env"] and job["env"]["HYPOTHESIS_PROFILE"] == "ci"
    assert _uses(job, "astral-sh/setup-uv") and "uv sync --frozen" in _runs(job)
    assert len(pytest_steps) == 1 and not pytest_steps[0].get("continue-on-error")
    assert _index(job, "df -T") < job["steps"].index(pytest_steps[0]), "D168: the data folder's filesystem is shown"
    assert 'uv run pytest -q $PENDING_FLAGS -m "slow and A_6"' in pytest_steps[0]["run"]
    expression = re.search(r'-m "(?P<expression>[^"]+)"', pytest_steps[0]["run"])
    assert expression is not None
    assert _collected_everywhere(expression["expression"]) == [A_6], "the job runs A-6 and nothing else"


def test_pre_push_selection_excludes_slow_and_solver_child_scenarios() -> None:
    """D199: pre-push stays under five minutes; it runs the in-process properties, never A-6 or the real solves."""
    collected = _collect("-m", "not slow and not solver_child", module=MODULE_02)

    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert A_6 not in collected.stdout and IDENTICAL_INPUTS not in collected.stdout
    missing = [name for name in SLICE_02_PROPERTIES if f"{MODULE_02}::{name}" not in collected.stdout]
    assert missing == []


def test_pre_push_selection_excludes_the_slow_slice_03_scenarios() -> None:
    """D199, D223: #13 starts no solve child, so only `slow` keeps its 30 s wait out of pre-push; #6 is a real solve."""
    hooks = {h["id"]: h for repo in yaml.safe_load(PRE_COMMIT.read_text())["repos"] for h in repo["hooks"]}
    expression = re.search(r'-m "(?P<expression>[^"]+)"', hooks["pytest-fast"]["entry"])
    assert expression is not None and expression["expression"] == "not slow and not solver_child"

    collected = _collected_slice_03("-m", expression["expression"])

    assert "test_stopping_while_roads_are_still_being_looked_up_changes_nothing" in collected, "the module collected"
    assert set(collected).isdisjoint({*SLOW_SLICE_03, GOLDEN_SCENARIO})


# ------------------------------------------------------------------- step 06-02: job 3 golden-order gates publish
GOLDEN_TESTS = ("test_the_reference_projects_plan_to_their_committed_golden_order",)


def test_golden_order_job_runs_the_golden_tests_and_the_golden_scenario() -> None:
    """DEVOPS row 3, D96, D223: I1 and I2 against their blessed order and slice 03's 60-item plan (#6) on every code
    change; real children, so not job 2."""
    workflow = _workflow()
    job = _job(workflow, "golden-order")
    pytest_steps = [s for s in job["steps"] if "pytest" in s.get("run", "")]
    job_2 = re.search(r'-m "(?P<expression>[^"]+)"', _main_pytest(_job(workflow, "test-python"))["run"])
    assert job_2 is not None

    assert job["name"] == "3 golden-order"
    assert _needs(job) == {"changes"} and job["if"] == "needs.changes.outputs.code == 'true'"
    assert job["timeout-minutes"] == 10
    assert job["env"] == {**_job(workflow, "slow-properties")["env"]}, "the set-up of slow-properties (D168)"
    assert _uses(job, "astral-sh/setup-uv") and "uv sync --frozen" in _runs(job)
    assert not _uses(job, "actions/setup-node"), "no web build and no browser"
    assert _index(job, "df -T") < job["steps"].index(pytest_steps[0]), "D168: the data folder's filesystem is shown"
    assert '"$PLANNER_TEST_WORKSPACE"' in _runs(job)[_index(job, "df -T")]
    assert len(pytest_steps) == 1 and not pytest_steps[0].get("continue-on-error")
    command = pytest_steps[0]["run"]
    # A bare pytest run: selecting nothing exits 5 and fails the job (no pytest-selection.sh, no `|| true`).
    assert "uv run pytest -q $PENDING_FLAGS -m golden_order\n" in command + "\n"
    assert "pytest-selection.sh" not in command and "||" not in command

    assert _collected_everywhere("golden_order") == sorted([*GOLDEN_TESTS, GOLDEN_SCENARIO])
    assert set(_collected_everywhere(job_2["expression"])).isdisjoint({*GOLDEN_TESTS, GOLDEN_SCENARIO})

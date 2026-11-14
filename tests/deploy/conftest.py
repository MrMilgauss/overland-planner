"""Fixtures for the offline deploy tests: a fake Pi install dir driven through the real deploy.sh, a throw-away git
checkout driven through the real `make deploy`, and a fake GHCR registry serving buildx provenance (D195).

External commands are the shims in tests/deploy/shims (PATH-prefixed); see shims/_shim.py for their behaviour.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
SHIMS = Path(__file__).resolve().parent / "shims"
IMAGE = "ghcr.io/mrmilgauss/overland-planner"
SOURCE = "https://github.com/MrMilgauss/overland-planner"
PLATFORMS = ("linux/amd64", "linux/arm64")


@dataclass(frozen=True)
class Release:
    digest: str
    git_sha: str
    commit_ts: str
    alembic_head: str

    @property
    def image(self) -> str:
        return f"{IMAGE}@{self.digest}"

    @property
    def labels(self) -> dict[str, str]:
        return {
            "org.opencontainers.image.revision": self.git_sha,
            "org.overland.commit-ts": self.commit_ts,
            "org.overland.alembic-head": self.alembic_head,
        }


def _release(char: str, ts: str, head: str) -> Release:
    return Release("sha256:" + char * 64, char * 40, ts, head)


OLDEST = _release("0", "2026-10-30T09:00:00Z", "0001_initial")
PREVIOUS = _release("1", "2026-11-01T09:00:00Z", "0001_initial")
CURRENT = _release("a", "2026-11-02T09:00:00Z", "0002_projects")
NEW = _release("b", "2026-11-03T07:30:00Z", "0003_auth")

PI_BIND = "192.168.1.10"  # a documentation-style placeholder, not a real address
BASIC_AUTH_USER = "ferri"
BASIC_AUTH_PASSWORD = 'sh4red "family" pw'  # noqa: S105 - test value
# What the gh shim answers to `gh auth token` (D196: the Mac's token, delivered to deploy.sh on ssh stdin).
GH_TOKEN = "fake-gh-token-for-d196-tests"  # noqa: S105  gitleaks:allow - test value, not a credential


def release_env_text(release: Release, extra: str = "") -> str:
    return (
        f"PLANNER_IMAGE={release.image}\nPLANNER_GIT_SHA={release.git_sha}\n{extra}"
        f"PLANNER_COMMIT_TS={release.commit_ts}\nPLANNER_ALEMBIC_HEAD={release.alembic_head}\n"
    )


@dataclass
class FakePi:
    """`~/apps/overland-planner` on the Pi as make deploy leaves it: compose.yaml, scripts/, .env, release pointers."""

    root: Path
    dir: Path = field(init=False)
    shim_home: Path = field(init=False)

    def __post_init__(self) -> None:
        self.dir = self.root / "overland-planner"
        self.shim_home = self.root / "shim"
        (self.dir / "scripts").mkdir(parents=True)
        self.shim_home.mkdir()
        shutil.copy(REPO / "deploy/compose.yaml", self.dir)
        for script in ("deploy.sh", "rollback.sh", "lib.sh"):
            source = REPO / "deploy/scripts" / script
            if source.exists():
                shutil.copy(source, self.dir / "scripts")
        (self.dir / ".env").write_text(
            f"PLANNER_BIND={PI_BIND}\nPLANNER_PORT=8080\nLOG_LEVEL=INFO\n"
            f"PLANNER_BASIC_AUTH_USER={BASIC_AUTH_USER}\nPLANNER_BASIC_AUTH_PASSWORD={BASIC_AUTH_PASSWORD}\n"
        )
        (self.dir / "release.env").write_text(
            release_env_text(CURRENT, extra="# pinned by Marco: keep\nPLANNER_NOTE=hand-written\nCOMPOSE_PROFILES=\n")
        )
        (self.dir / "release.env.prev").write_text(release_env_text(PREVIOUS))
        (self.dir / "release.env.prev2").write_text(release_env_text(OLDEST))
        (self.dir / "releases.log").write_text('{"ts":"2026-11-02T09:10:00Z","action":"deploy","result":"ok"}\n')
        images = {release.digest: release.labels for release in (OLDEST, PREVIOUS, CURRENT, NEW)}
        (self.shim_home / "images.json").write_text(json.dumps(images))
        self.originals = {name: (self.dir / name).read_text() for name in self.pointer_files}

    pointer_files = ("release.env", "release.env.prev", "release.env.prev2")

    def rule(self, tool: str, *args_contain: str, **answer: Any) -> None:
        rules_file = self.shim_home / "rules.json"
        rules = json.loads(rules_file.read_text()) if rules_file.exists() else []
        rules.append({"tool": tool, "args_contain": list(args_contain), **answer})
        rules_file.write_text(json.dumps(rules))

    def deploy(self, digest: str, token: str = GH_TOKEN) -> subprocess.CompletedProcess[str]:
        """deploy.sh as make deploy runs it: the GHCR token on stdin (D196)."""
        return subprocess.run(
            ["bash", str(self.dir / "scripts/deploy.sh"), digest],
            input=f"{token}\n" if token else "",
            cwd=self.root,
            env=shim_env(self.shim_home),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def rollback(self, *steps: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.dir / "scripts/rollback.sh"), *steps],
            cwd=self.root,
            env=shim_env(self.shim_home),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def calls(self, tool: str | None = None) -> list[dict[str, Any]]:
        log = self.shim_home / "calls.jsonl"
        records = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [record for record in records if tool is None or record["tool"] == tool]

    def releases_log(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in (self.dir / "releases.log").read_text().splitlines()]

    def pointers(self) -> dict[str, str]:
        return {name: (self.dir / name).read_text() for name in self.pointer_files}


def shim_env(shim_home: Path, **extra: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PLANNER_", "GH_", "GITHUB_"))}
    env.update(PATH=f"{SHIMS}{os.pathsep}{os.environ['PATH']}", SHIM_HOME=str(shim_home), **extra)
    return env


@pytest.fixture
def pi(tmp_path: Path) -> FakePi:
    return FakePi(tmp_path)


# ---- fake GHCR (registry API v2 with token auth) ----------------------------------------------------------------


def _blob(document: dict[str, Any]) -> tuple[bytes, str]:
    data = json.dumps(document).encode()
    return data, "sha256:" + hashlib.sha256(data).hexdigest()


class FakeRegistry:
    """Serves one manifest list with a platform manifest + buildx attestation manifest per platform."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fetched: dict[
            str, str
        ] = {}  # what the verifier fetches -> its digest: index, attestation:<p>, provenance:<p>
        self.refuse_token = False
        self.digest = ""
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def publish(
        self, vcs_by_platform: dict[str, dict[str, str] | None], subjects: dict[str, list[dict[str, Any]]] | None = None
    ) -> str:
        """Store an image whose provenance names `vcs_by_platform[p]` (None = no attestation); return its digest.

        The in-toto statement's `subject` names the platform image manifest (as buildx writes it) unless `subjects[p]`
        replaces it."""
        self.objects.clear()
        self.fetched.clear()
        entries: list[dict[str, Any]] = []
        for platform in PLATFORMS:
            os_name, arch = platform.split("/")
            data, image_digest = _blob({"schemaVersion": 2, "config": {}, "layers": [], "arch": arch})
            self.objects[image_digest] = data
            entries.append({"digest": image_digest, "platform": {"architecture": arch, "os": os_name}})
            vcs = vcs_by_platform.get(platform)
            if vcs is None:
                continue
            subject = [
                {
                    "name": f"pkg:docker/{IMAGE}@sha-x?platform={os_name}%2F{arch}",
                    "digest": {"sha256": image_digest.removeprefix("sha256:")},
                }
            ]
            statement = {
                "_type": "https://in-toto.io/Statement/v0.1",
                "predicateType": "https://slsa.dev/provenance/v0.2",
                "subject": (subjects or {}).get(platform, subject),
                "predicate": {
                    "builder": {"id": ""},
                    "metadata": {"https://mobyproject.org/buildkit@v1#metadata": {"vcs": vcs}},
                },
            }
            layer, layer_digest = _blob(statement)
            sbom, sbom_digest = _blob({"predicateType": "https://spdx.dev/Document", "predicate": {}})
            self.objects[layer_digest] = layer
            self.objects[sbom_digest] = sbom
            attestation, attestation_digest = _blob(
                {
                    "schemaVersion": 2,
                    "layers": [
                        {
                            "digest": sbom_digest,
                            "annotations": {"in-toto.io/predicate-type": "https://spdx.dev/Document"},
                        },
                        {
                            "digest": layer_digest,
                            "annotations": {"in-toto.io/predicate-type": "https://slsa.dev/provenance/v0.2"},
                        },
                    ],
                }
            )
            self.objects[attestation_digest] = attestation
            self.fetched |= {f"attestation:{platform}": attestation_digest, f"provenance:{platform}": layer_digest}
            entries.append(
                {
                    "digest": attestation_digest,
                    "platform": {"architecture": "unknown", "os": "unknown"},
                    "annotations": {
                        "vnd.docker.reference.digest": image_digest,
                        "vnd.docker.reference.type": "attestation-manifest",
                    },
                }
            )
        index, self.digest = _blob({"schemaVersion": 2, "manifests": entries})
        self.objects[self.digest] = index
        self.fetched["index"] = self.digest
        return self.digest

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        registry = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                if self.path.startswith("/token"):
                    if registry.refuse_token or not self.headers.get("Authorization", "").startswith("Basic "):
                        self._send(401, b'{"errors":[{"code":"DENIED"}]}')
                    else:
                        self._send(200, b'{"token":"registry-token"}')
                    return
                if self.headers.get("Authorization") != "Bearer registry-token":
                    self._send(401, b"{}")
                    return
                prefix = "/v2/mrmilgauss/overland-planner/"
                reference = self.path.removeprefix(prefix).split("/", 1)[-1]
                data = registry.objects.get(reference)
                self._send(200, data) if data is not None and self.path.startswith(prefix) else self._send(404, b"{}")

            def _send(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def close(self) -> None:
        self._server.shutdown()


@pytest.fixture
def registry() -> Iterator[FakeRegistry]:
    fake = FakeRegistry()
    yield fake
    fake.close()


# ---- the Mac side: a clean checkout running `make deploy` --------------------------------------------------------


@dataclass
class MacCheckout:
    root: Path
    registry: FakeRegistry
    dir: Path = field(init=False)
    shim_home: Path = field(init=False)

    def __post_init__(self) -> None:
        self.dir = self.root / "checkout"
        self.shim_home = self.root / "shim"
        self.shim_home.mkdir()
        (self.dir / "deploy").mkdir(parents=True)
        shutil.copy(REPO / "Makefile", self.dir)
        shutil.copy(REPO / "deploy/compose.yaml", self.dir / "deploy")
        if (REPO / "deploy/scripts").is_dir():
            shutil.copytree(
                REPO / "deploy/scripts", self.dir / "deploy/scripts", ignore=shutil.ignore_patterns("__pycache__")
            )
        (self.dir / ".gitignore").write_text(".data/\n")
        git = ["git", "-C", str(self.dir), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "checkout"], check=True)

    def rule(self, tool: str, *args_contain: str, **answer: Any) -> None:
        rules_file = self.shim_home / "rules.json"
        rules = json.loads(rules_file.read_text()) if rules_file.exists() else []
        rules.append({"tool": tool, "args_contain": list(args_contain), **answer})
        rules_file.write_text(json.dumps(rules))

    def green_run(self, sha: str, digest: str, run_id: int = 4242, release_json: bool = True) -> None:
        """Script gh: run `run_id` is a successful ci.yml push run on main for `sha`, with or without release.json."""
        self.rule("gh", "run list", "--commit", sha, stdout=f"{run_id}\n")
        self.rule("gh", "run list", stdout=f"{run_id} {sha}\n")
        if release_json:
            body = {"git_sha": sha, "commit_ts": NEW.commit_ts, "digest": digest, "alembic_head": "0003_auth"}
            self.rule("gh", "run download", str(run_id), release_json={**body, "provenance": "buildx"})
        else:
            self.rule(
                "gh", "run download", exit=1, stderr="no artifact matches any of the names or patterns provided\n"
            )
        self.rule("gh", "auth token", stdout=f"{GH_TOKEN}\n")

    def make_deploy(self, *variables: str) -> subprocess.CompletedProcess[str]:
        return self.make("deploy", *variables)

    def make_rollback(self, *variables: str) -> subprocess.CompletedProcess[str]:
        return self.make("rollback", *variables)

    def make(self, target: str, *variables: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["make", "-s", "-C", str(self.dir), target, "PI_HOST=deploy@pi.example", *variables],
            env=shim_env(self.shim_home, GHCR_URL=self.registry.url),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def calls(self, tool: str | None = None) -> list[dict[str, Any]]:
        log = self.shim_home / "calls.jsonl"
        records = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [record for record in records if tool is None or record["tool"] == tool]


@pytest.fixture
def mac(tmp_path: Path, registry: FakeRegistry) -> MacCheckout:
    return MacCheckout(tmp_path, registry)

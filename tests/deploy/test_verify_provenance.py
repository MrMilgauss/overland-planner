"""D195 decision rule of deploy/scripts/verify_provenance.py: deploy only when the buildx provenance of BOTH platforms
names github.com/mrmilgauss/overland-planner (any case, optional .git) at the release git SHA. Mirrors the CI publish
step "Verify the buildx provenance of both platforms". The in-toto statement's subject must be the platform image
(F10); every object fetched must match its digest; a bad release.json, an unreachable or odd registry refuse cleanly."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.deploy.conftest import FakeRegistry

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/scripts/verify_provenance.py"
PLATFORMS = ("linux/amd64", "linux/arm64")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_provenance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = _load()

shas = st.text("0123456789abcdef", min_size=40, max_size=40)
spellings = st.sampled_from(
    [
        "https://github.com/MrMilgauss/overland-planner",
        "https://github.com/mrmilgauss/overland-planner.git",
        "https://github.com/MRMILGAUSS/Overland-Planner.git",
    ]
)


def predicate(source: str, revision: str) -> dict[str, Any]:
    """The SLSA v0.2 predicate buildx attaches (mode=max): vcs sits in the buildkit metadata."""
    return {
        "metadata": {"https://mobyproject.org/buildkit@v1#metadata": {"vcs": {"source": source, "revision": revision}}}
    }


@given(sha=shas, spelling=spellings)
def test_accepts_when_both_platforms_name_the_repository_at_the_release_sha(sha: str, spelling: str) -> None:
    vcs = {platform: verify.vcs_of(predicate(spelling, sha)) for platform in PLATFORMS}

    assert verify.provenance_errors(vcs, sha) == []


@given(
    sha=shas,
    spelling=spellings,
    broken=st.sampled_from(PLATFORMS),
    defect=st.sampled_from(["other revision", "other repository", "no provenance", "no vcs"]),
    other=shas,
)
def test_refuses_when_either_platform_is_missing_or_mismatched(
    sha: str, spelling: str, broken: str, defect: str, other: str
) -> None:
    good = predicate(spelling, sha)
    bad: dict[str, Any] | None = {
        "other revision": predicate(spelling, other if other != sha else "f" * 40 if sha != "f" * 40 else "e" * 40),
        "other repository": predicate("https://github.com/someone-else/overland-planner", sha),
        "no provenance": None,
        "no vcs": {"metadata": {}},
    }[defect]
    vcs = {platform: verify.vcs_of(bad if platform == broken else good) for platform in PLATFORMS}

    errors = verify.provenance_errors(vcs, sha)

    assert len(errors) == 1 and broken in errors[0]


# ---- the whole gate against the fake GHCR (tests/deploy/conftest.py): integrity, release.json, subject, I/O --------
# Example-based (# bypass: each case is one named way the registry, release.json or the network goes wrong).

SHA = "c" * 40
OTHER_IMAGE = "d" * 64


def _gate(
    registry: FakeRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    **json_or_text: Any,
) -> tuple[int, str, str]:
    """Run the gate as `make deploy` does (GH_TOKEN stands in for `gh auth token`); (exit code, stdout, stderr)."""
    release = tmp_path / "release.json"
    text = json_or_text.get("text")
    release.write_text(
        text
        if text is not None
        else json.dumps(json_or_text.get("release", {"git_sha": SHA, "digest": registry.digest}))
    )
    monkeypatch.setenv("GHCR_URL", json_or_text.get("url", registry.url))
    monkeypatch.setenv("GH_TOKEN", "fake-pat")
    code = verify.main(["--release-json", str(release), "--sha", SHA])
    out, err = capsys.readouterr()
    return code, out, err


def _good(registry: FakeRegistry) -> str:
    return registry.publish(
        {p: {"source": "https://github.com/MrMilgauss/overland-planner", "revision": SHA} for p in PLATFORMS}
    )


def test_an_intact_release_prints_its_digest(
    registry: FakeRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    digest = _good(registry)
    assert _gate(registry, tmp_path, monkeypatch, capsys) == (0, f"{digest}\n", "")


@pytest.mark.parametrize("tampered", ["index", "attestation:linux/arm64", "provenance:linux/amd64"])
def test_content_that_does_not_match_its_digest_is_refused(
    registry: FakeRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tampered: str,
) -> None:
    _good(registry)
    digest = registry.fetched[tampered]
    registry.objects[digest] = registry.objects[digest].replace(b"overland-planner", b"overland-p1anner") + b" "

    code, out, err = _gate(registry, tmp_path, monkeypatch, capsys)

    assert (code, out) == (1, "")
    assert err == f"provenance: GHCR returned content that does not match {digest}\n"


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ([{"name": "pkg:docker/x", "digest": {"sha256": OTHER_IMAGE}}], "names other images"),
        ([], "names other images"),
        ("not-a-list", "names other images"),
    ],
)
def test_a_statement_whose_subject_is_not_the_platform_image_is_refused(
    registry: FakeRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    subject: Any,
    expected: str,
) -> None:
    vcs = {"source": "https://github.com/MrMilgauss/overland-planner", "revision": SHA}
    registry.publish({p: vcs for p in PLATFORMS}, subjects={"linux/arm64": subject})

    code, out, err = _gate(registry, tmp_path, monkeypatch, capsys)

    assert (code, out) == (1, "")
    assert err.startswith("provenance: linux/arm64 provenance statement ") and expected in err
    assert "linux/amd64" not in err


@pytest.mark.parametrize(
    ("release", "text", "expected"),
    [
        ({"git_sha": "e" * 40, "digest": "sha256:" + "a" * 64}, None, "not the SHA being deployed"),
        ({"git_sha": SHA, "digest": "sha256:XYZ"}, None, "no valid manifest-list digest"),
        ({"git_sha": SHA}, None, "no valid manifest-list digest"),
        (None, "{not json", "release.json is not readable JSON"),
        (None, "[1, 2]", "release.json is not readable JSON"),
    ],
)
def test_a_release_json_that_does_not_name_this_release_is_refused(
    registry: FakeRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    release: dict[str, str] | None,
    text: str | None,
    expected: str,
) -> None:
    _good(registry)
    code, out, err = _gate(registry, tmp_path, monkeypatch, capsys, release=release, text=text)

    assert (code, out) == (1, "")
    assert err.startswith("provenance: release.json ") and expected in err and "Traceback" not in err


def test_an_unreachable_registry_is_refused_with_a_clean_message(
    registry: FakeRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _good(registry)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{probe.getsockname()[1]}"  # nothing listens once the socket is closed

    code, out, err = _gate(registry, tmp_path, monkeypatch, capsys, url=closed)

    assert (code, out) == (1, "")
    assert err.startswith(f"provenance: GHCR unreachable at {closed}: ") and err.count("\n") == 1


def test_a_registry_answering_an_unexpected_document_is_refused(
    registry: FakeRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    index = b'["not", "an", "index"]'
    registry.objects.clear()
    registry.digest = "sha256:" + hashlib.sha256(index).hexdigest()
    registry.objects[registry.digest] = index

    code, out, err = _gate(registry, tmp_path, monkeypatch, capsys)

    assert (code, out) == (1, "")
    assert err.startswith("provenance: GHCR answered an unexpected document") and err.count("\n") == 1

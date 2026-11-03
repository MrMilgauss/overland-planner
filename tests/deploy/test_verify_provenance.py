"""D195 decision rule of deploy/scripts/verify_provenance.py: deploy only when the buildx provenance of BOTH platforms
names github.com/mrmilgauss/overland-planner (any case, optional .git) at the release git SHA. Mirrors the CI publish
step "Verify the buildx provenance of both platforms"."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

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

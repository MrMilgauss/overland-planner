#!/usr/bin/env python3
"""Release gate of `make deploy` on the Mac (D171 replaced by D195; stdlib only, the Mac has no Docker).

    verify_provenance.py --release-json <release.json from a green ci.yml run> --sha <git sha being deployed>

1. release.json must name the SHA being deployed; its `digest` is the manifest list to deploy.
2. The manifest list is read from GHCR with a pull token obtained from `gh auth token` (needs read:packages). Every
   object fetched is checked against its digest, so the registry cannot substitute content.
3. For linux/amd64 and linux/arm64, the buildx attestation manifest (`vnd.docker.reference.type:
   attestation-manifest`) is followed to its in-toto SLSA provenance layer. Both platforms must name
   https://github.com/mrmilgauss/overland-planner (lowercased, `.git` stripped) at the release SHA: the same rule as
   the CI publish step "Verify the buildx provenance of both platforms". Missing or mismatching provenance refuses.

Prints the digest on success; exits non-zero with the reasons on stderr otherwise (fail closed).
GHCR_URL overrides the registry base URL (offline tests only).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

REPOSITORY = "mrmilgauss/overland-planner"
EXPECTED_SOURCE = f"https://github.com/{REPOSITORY}"
PLATFORMS = ("linux/amd64", "linux/arm64")
GHCR_USER = "MrMilgauss"
INDEX_TYPES = "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json"
MANIFEST_TYPES = "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"
NO_PACKAGES_SCOPE = "gh token lacks read:packages — run: gh auth refresh -h github.com -s read:packages"


class Refused(Exception):
    """The release must not be deployed."""


# ---- decision (pure) ---------------------------------------------------------------------------------------------


def _objects(node: Any) -> Iterator[Mapping[str, Any]]:
    """Every object in the document, depth-first in document order (jq `.. | objects`)."""
    if isinstance(node, Mapping):
        yield node
        for value in node.values():
            yield from _objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _objects(value)


def vcs_of(predicate: Any) -> Mapping[str, Any] | None:
    """The first `vcs` object of a SLSA provenance predicate, wherever buildx put it (v0.2 or v1)."""
    return next((obj["vcs"] for obj in _objects(predicate) if isinstance(obj.get("vcs"), Mapping)), None)


def _normalised(source: str) -> str:
    source = source.lower()
    return source[: -len(".git")] if source.endswith(".git") else source


def provenance_errors(vcs_by_platform: Mapping[str, Mapping[str, Any] | None], sha: str) -> list[str]:
    """One error per platform whose provenance does not name this repository at `sha`; empty = deployable."""
    errors = []
    for platform in PLATFORMS:
        vcs = vcs_by_platform.get(platform) or {}
        source = _normalised(str(vcs.get("source") or ""))
        revision = str(vcs.get("revision") or "")
        if source != EXPECTED_SOURCE or revision != sha:
            errors.append(
                f"{platform} provenance names '{source}' at '{revision}', expected {EXPECTED_SOURCE} at {sha}"
            )
    return errors


# ---- registry I/O ------------------------------------------------------------------------------------------------


class Registry:
    def __init__(self, base_url: str, pat: str) -> None:
        if not base_url.startswith(("https://", "http://")):
            raise Refused(f"registry URL must be http(s): {base_url!r}")
        self._base = base_url.rstrip("/")
        self._token = self._pull_token(pat)

    def _pull_token(self, pat: str) -> str:
        basic = base64.b64encode(f"{GHCR_USER}:{pat}".encode()).decode()
        request = urllib.request.Request(f"{self._base}/token?scope=repository:{REPOSITORY}:pull&service=ghcr.io")  # noqa: S310
        request.add_unredirected_header("Authorization", f"Basic {basic}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - scheme checked in __init__
                return str(json.load(response)["token"])
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise Refused(NO_PACKAGES_SCOPE) from error
            raise Refused(f"GHCR token request failed: HTTP {error.code}") from error

    def fetch(self, kind: str, digest: str, accept: str = "") -> Any:
        request = urllib.request.Request(f"{self._base}/v2/{REPOSITORY}/{kind}/{digest}")  # noqa: S310
        request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        if accept:
            request.add_header("Accept", accept)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - scheme checked in __init__
                data = response.read()
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise Refused(NO_PACKAGES_SCOPE) from error
            raise Refused(f"GHCR {kind}/{digest}: HTTP {error.code}") from error
        if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
            raise Refused(f"GHCR returned content that does not match {digest}")
        return json.loads(data)


def provenance_by_platform(registry: Registry, digest: str) -> dict[str, Mapping[str, Any] | None]:
    index = registry.fetch("manifests", digest, INDEX_TYPES)
    entries = index.get("manifests", [])
    images = {
        f"{entry.get('platform', {}).get('os')}/{entry.get('platform', {}).get('architecture')}": entry["digest"]
        for entry in entries
    }
    attestations = {
        entry.get("annotations", {}).get("vnd.docker.reference.digest"): entry["digest"]
        for entry in entries
        if entry.get("annotations", {}).get("vnd.docker.reference.type") == "attestation-manifest"
    }
    found: dict[str, Mapping[str, Any] | None] = {}
    for platform in PLATFORMS:
        attestation = attestations.get(images.get(platform))
        found[platform] = None
        if attestation is None:
            continue
        manifest = registry.fetch("manifests", attestation, MANIFEST_TYPES)
        for layer in manifest.get("layers", []):
            predicate_type = layer.get("annotations", {}).get("in-toto.io/predicate-type", "")
            if predicate_type.startswith("https://slsa.dev/provenance/"):
                found[platform] = vcs_of(registry.fetch("blobs", layer["digest"]).get("predicate"))
                break
    return found


# ---- command line ------------------------------------------------------------------------------------------------


def _release_digest(release_json: Path, sha: str) -> str:
    release = json.loads(release_json.read_text())
    if release.get("git_sha") != sha:
        raise Refused(f"release.json names {release.get('git_sha')!r}, not the SHA being deployed {sha}")
    digest = str(release.get("digest") or "")
    hex_part = digest.removeprefix("sha256:")
    if not digest.startswith("sha256:") or len(hex_part) != 64 or set(hex_part) - set("0123456789abcdef"):
        raise Refused(f"release.json has no valid manifest-list digest: {digest!r}")
    return digest


def _gh_token() -> str:
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)  # noqa: S607 - gh from PATH
    if result.returncode != 0 or not result.stdout.strip():
        raise Refused("gh is not logged in — run: gh auth login -h github.com -s read:packages")
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release-json", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args(argv)
    try:
        digest = _release_digest(args.release_json, args.sha)
        registry = Registry(os.environ.get("GHCR_URL", "https://ghcr.io"), _gh_token())
        errors = provenance_errors(provenance_by_platform(registry, digest), args.sha)
        if errors:
            raise Refused("; ".join(errors))
    except Refused as refusal:
        print(f"provenance: {refusal}", file=sys.stderr)
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

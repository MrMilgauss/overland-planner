#!/usr/bin/env python3
"""Release gate of `make deploy` on the Mac (D171 replaced by D195; stdlib only, the Mac has no Docker).

    verify_provenance.py --release-json <release.json from a green ci.yml run> --sha <git sha being deployed>

1. release.json must name the SHA being deployed; its `digest` is the manifest list to deploy.
2. The manifest list is read from GHCR with a pull token obtained from `gh auth token` (needs read:packages). Every
   object fetched is checked against its digest, so the registry cannot substitute content.
3. For linux/amd64 and linux/arm64, the buildx attestation manifest (`vnd.docker.reference.type:
   attestation-manifest`) is followed to its in-toto SLSA provenance layer. Both platforms must name
   https://github.com/mrmilgauss/overland-planner (lowercased, `.git` stripped) at the release SHA: the same rule as
   the CI publish step "Verify the buildx provenance of both platforms". The in-toto statement's `subject` must name
   that platform's image manifest (the digest listed in the manifest list), so a statement copied from another image
   refuses too. Missing or mismatching provenance refuses.

Prints the digest on success; exits non-zero with one reason line on stderr otherwise (fail closed): an unreadable
release.json, an unreachable registry or a document of an unexpected shape refuse the same way, never a traceback.
GH_TOKEN, when set, is used instead of `gh auth token` (the CI publish job runs this gate with its GITHUB_TOKEN);
GHCR_USER overrides the registry user (CI: the workflow actor). GHCR_URL overrides the registry base URL (offline
tests only).
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
from typing import Any, NamedTuple

REPOSITORY = "mrmilgauss/overland-planner"
EXPECTED_SOURCE = f"https://github.com/{REPOSITORY}"
PLATFORMS = ("linux/amd64", "linux/arm64")
GHCR_USER = os.environ.get("GHCR_USER") or "MrMilgauss"
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


class Attested(NamedTuple):
    """One platform of the manifest list: its image manifest digest and its in-toto statement (None = none found)."""

    image: str
    statement: Mapping[str, Any] | None


def vcs_by_platform(found: Mapping[str, Attested]) -> dict[str, Mapping[str, Any] | None]:
    return {
        platform: vcs_of(attested.statement.get("predicate")) if attested.statement is not None else None
        for platform, attested in found.items()
    }


def subject_errors(found: Mapping[str, Attested]) -> list[str]:
    """One error per platform whose in-toto statement is not about that platform's image manifest."""
    errors = []
    for platform in PLATFORMS:
        attested = found.get(platform)
        if attested is None or attested.statement is None:
            continue  # no provenance at all: provenance_errors already names the platform
        subject = attested.statement.get("subject")
        named = {
            "sha256:" + str(entry["digest"]["sha256"])
            for entry in (subject if isinstance(subject, list) else [])
            if isinstance(entry, Mapping) and isinstance(entry.get("digest"), Mapping) and "sha256" in entry["digest"]
        }
        if attested.image not in named:
            errors.append(f"{platform} provenance statement names other images {sorted(named)}, not {attested.image}")
    return errors


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

    def _open(self, request: urllib.request.Request, timeout: int) -> bytes:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - scheme checked in __init__
                return bytes(response.read())
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise Refused(f"GHCR unreachable at {self._base}: {reason}") from error

    def _pull_token(self, pat: str) -> str:
        basic = base64.b64encode(f"{GHCR_USER}:{pat}".encode()).decode()
        request = urllib.request.Request(f"{self._base}/token?scope=repository:{REPOSITORY}:pull&service=ghcr.io")  # noqa: S310
        request.add_unredirected_header("Authorization", f"Basic {basic}")
        try:
            return str(json.loads(self._open(request, timeout=30))["token"])
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
            data = self._open(request, timeout=60)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise Refused(NO_PACKAGES_SCOPE) from error
            raise Refused(f"GHCR {kind}/{digest}: HTTP {error.code}") from error
        if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
            raise Refused(f"GHCR returned content that does not match {digest}")
        return json.loads(data)


def provenance_by_platform(registry: Registry, digest: str) -> dict[str, Attested]:
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
    found: dict[str, Attested] = {}
    for platform in PLATFORMS:
        image = images.get(platform, "")
        found[platform] = Attested(image, None)
        attestation = attestations.get(image)
        if attestation is None:
            continue
        manifest = registry.fetch("manifests", attestation, MANIFEST_TYPES)
        for layer in manifest.get("layers", []):
            predicate_type = layer.get("annotations", {}).get("in-toto.io/predicate-type", "")
            if predicate_type.startswith("https://slsa.dev/provenance/"):
                found[platform] = Attested(image, registry.fetch("blobs", layer["digest"]))
                break
    return found


# ---- command line ------------------------------------------------------------------------------------------------


def _release_digest(release_json: Path, sha: str) -> str:
    try:
        release = json.loads(release_json.read_text())
    except (OSError, ValueError) as error:
        raise Refused(f"release.json is not readable JSON: {error}") from error
    if not isinstance(release, Mapping):
        raise Refused(f"release.json is not readable JSON: a {type(release).__name__}, not an object")
    if release.get("git_sha") != sha:
        raise Refused(f"release.json names {release.get('git_sha')!r}, not the SHA being deployed {sha}")
    digest = str(release.get("digest") or "")
    hex_part = digest.removeprefix("sha256:")
    if not digest.startswith("sha256:") or len(hex_part) != 64 or set(hex_part) - set("0123456789abcdef"):
        raise Refused(f"release.json has no valid manifest-list digest: {digest!r}")
    return digest


def _gh_token() -> str:
    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"]
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)  # noqa: S607 - gh from PATH
    if result.returncode != 0 or not result.stdout.strip():
        raise Refused("gh is not logged in — run: gh auth login -h github.com -s read:packages")
    return result.stdout.strip()


def _registry_view(registry: Registry, digest: str) -> dict[str, Attested]:
    try:
        return provenance_by_platform(registry, digest)
    except (ValueError, KeyError, TypeError, AttributeError) as error:  # JSONDecodeError is a ValueError
        raise Refused(f"GHCR answered an unexpected document for {digest}: {type(error).__name__}") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release-json", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args(argv)
    try:
        digest = _release_digest(args.release_json, args.sha)
        registry = Registry(os.environ.get("GHCR_URL", "https://ghcr.io"), _gh_token())
        found = _registry_view(registry, digest)
        errors = provenance_errors(vcs_by_platform(found), args.sha) + subject_errors(found)
        if errors:
            raise Refused("; ".join(errors))
    except Refused as refusal:
        print(f"provenance: {refusal}", file=sys.stderr)
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Prune the GHCR package to the release just published (CI job 9, step 01-09, D169).

Keeps the manifest list of this release, every manifest it references (per-arch images and their SBOM/provenance
attestation manifests, recursively) and every manifest whose OCI `subject` is a kept one (the GitHub attestation of
the list). Deletes every other version. Fail-safe: if anything is ambiguous (the release is not listed, a manifest
cannot be read, the `main` tag sits on another version) nothing is deleted and the reason goes to the job summary.

Usage: ghcr_prune.py --owner OWNER --package NAME --digest sha256:... [--owner-type users|orgs] [--dry-run]
Needs `gh` (GH_TOKEN with packages write) and `docker buildx imagetools` logged in to ghcr.io.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Version = dict[str, Any]
ManifestReader = Callable[[str], "dict[str, Any] | None"]
INDEX_TYPES = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")


@dataclass
class Plan:
    keep: set[str] = field(default_factory=set)
    delete: list[Version] = field(default_factory=list)
    skip_reason: str | None = None


def _tags(version: Version) -> list[str]:
    return list(version.get("metadata", {}).get("container", {}).get("tags", []))


def _skip(reason: str) -> Plan:
    return Plan(skip_reason=reason)


def decide(versions: list[Version], release: str, read_manifest: ManifestReader) -> Plan:
    """Which package versions to delete so that only `release` and what belongs to it remain."""
    listed = {v["name"]: v for v in versions}
    if release not in listed:
        return _skip(f"the release {release} is not listed among the package versions")
    keep: set[str] = set()
    pending = [release]
    while pending:  # the release and everything it references
        digest = pending.pop()
        if digest in keep:
            continue
        keep.add(digest)
        manifest = read_manifest(digest)
        if manifest is None:
            if digest in listed:
                return _skip(f"cannot read the manifest {digest}")
            continue
        pending.extend(child["digest"] for child in manifest.get("manifests", []))
    changed = True
    while changed:  # manifests attached to a kept one through `subject` (attestations, referrer indexes)
        changed = False
        for digest in listed.keys() - keep:
            manifest = read_manifest(digest)
            if manifest is None:
                return _skip(f"cannot read the manifest {digest}")
            if manifest.get("subject", {}).get("digest") in keep:
                keep.add(digest)
                keep.update(child["digest"] for child in manifest.get("manifests", []))
                changed = True
    delete = [v for v in versions if v["name"] not in keep]
    tagged_main = [v["name"] for v in delete if "main" in _tags(v)]
    if tagged_main:
        return _skip(f"the main tag is on {tagged_main}, not on the release")
    return Plan(keep=keep, delete=delete)


def _gh(*args: str) -> str:
    # gh from the runner PATH; arguments are built here from the workflow's own context, never from user input.
    return subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=True).stdout


def _manifest_reader(image: str) -> ManifestReader:
    cache: dict[str, dict[str, Any] | None] = {}

    def read(digest: str) -> dict[str, Any] | None:
        if digest not in cache:
            run = subprocess.run(  # digests come from the GHCR listing of our own package
                ["docker", "buildx", "imagetools", "inspect", "--raw", f"{image}@{digest}"],
                capture_output=True,
                text=True,
                check=False,
            )
            try:
                cache[digest] = json.loads(run.stdout) if run.returncode == 0 else None
            except json.JSONDecodeError:
                cache[digest] = None
        return cache[digest]

    return read


def _report(lines: list[str]) -> None:
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(text + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--owner", required=True)
    parser.add_argument("--owner-type", choices=("users", "orgs"), default="users")
    parser.add_argument("--package", required=True)
    parser.add_argument("--digest", required=True, help="digest of the manifest list just published")
    parser.add_argument("--dry-run", action="store_true", help="report the decision, delete nothing")
    args = parser.parse_args()

    endpoint = f"/{args.owner_type}/{args.owner}/packages/container/{args.package}/versions"
    try:
        listing = _gh("--paginate", f"{endpoint}?per_page=100", "--jq", ".[]")
    except subprocess.CalledProcessError as error:
        _report(["### GHCR prune skipped", f"cannot list the package versions: {error.stderr.strip()}"])
        return 0
    versions = [json.loads(line) for line in listing.splitlines() if line.strip()]
    plan = decide(versions, args.digest, _manifest_reader(f"ghcr.io/{args.owner.lower()}/{args.package}"))
    if plan.skip_reason:
        _report(["### GHCR prune skipped (nothing deleted)", plan.skip_reason])
        return 0

    mode = "dry run, nothing deleted" if args.dry_run else "deleting"
    lines = [f"### GHCR prune ({mode})", f"keeping {len(plan.keep)} manifests of {args.digest}"]
    failed = 0
    for version in plan.delete:
        lines.append(f"- {version['name']} {_tags(version) or '(untagged)'}")
        if args.dry_run:
            continue
        try:
            _gh("-X", "DELETE", f"{endpoint}/{version['id']}")
        except subprocess.CalledProcessError as error:
            failed += 1
            lines.append(f"  - delete failed: {error.stderr.strip()}")
    _report(lines)
    if failed:
        print(f"::warning::GHCR prune could not delete {failed} version(s); see the job summary", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Overland Route Planner

Plans overland trips on a home Raspberry Pi. Requirements: [REQUIREMENTS.md](REQUIREMENTS.md).

## Developer quick start

Needs `uv`, Node 22 (`web/.nvmrc`) and `make`. Docker is needed only for the image and the `@requires_external`
scenarios.

```sh
make bootstrap   # locked Python dependencies and the pre-commit / pre-push hooks
make lint        # ruff, mypy --strict, import-linter
make test        # fast suite (builds web/dist first)
make test-web    # npm ci, svelte-check, vitest, vite build
make run-local   # the planner on http://127.0.0.1:8080 with the offline mock road map
make e2e-local   # Playwright home page and workspace journey (chromium, webkit-iphone14) against run-local
make mutate      # mutmut on domain/application files changed since origin/main (kill rate >= 80 %)
```

Acceptance scenarios tagged `@pending` run with `--run-pending=<slice>`; `@requires_external` ones with
`--run-external` on the right host. CI enables slices 00b and 01a (`PENDING_FLAGS` in ci.yml, D170).

## Using the planner

Open the planner in a browser (desktop or phone). The home page lists the **Projects**, shows every warning the
planner's health reports (e.g. a data folder that would not survive a restart) and creates a **New project**. In a
project's workspace (`#/projects/<id>`) Marco imports GPX trails, adds places by decimal degrees (latitude,
longitude) and chooses the trip's Start and End; the item list shows each item's type, name, the **Included** badge
and the **S/E**, **Start** or **End** badge. A refusal is shown with the planner's own message. The upload caps
(`MAX_UPLOAD_FILE_MB`, `MAX_UPLOAD_REQUEST_MB`, `MAX_UPLOAD_FILES`) are set in `.env`; empty means the default.

## CI

`.github/workflows/ci.yml`: lint, test-python and test-web on every push and pull request; on main pushes the
image jobs (amd64, arm64), e2e on the amd64 image, scoped mutation testing and publish. The image jobs push with
buildx in-registry SBOM and provenance (no GitHub attestations, D195). Publish creates the manifest list
`ghcr.io/mrmilgauss/overland-planner:sha-<12>` and `:main`, fails unless the provenance of both platforms names this
repository and commit, uploads `release.json` and prunes GHCR to that release. `.github/workflows/weekly.yml`
re-scans `main`, audits dependencies, runs the deep property profile and reports storage; deploys never wait for it.

### CI budget

| Item | Value |
| --- | --- |
| Compressed image size, amd64 | 135.7 MB (release `sha256:83a835f8…`, 2026-11-03) |
| Compressed image size, arm64 | 132.3 MB (same release; one release ≈ 268 MB of the 500 MB GHCR budget) |
| Actions minutes per main push | ≈ 18 billed min (run 41603868244: 9.2 min wall; per-job rounding), + ≈ 1 when the mutation job runs |

## Operations (the Pi)

The planner runs on Marco's Raspberry Pi 5 (the deploy user's login and the install dir are in the git-ignored `deploy/pi.env`, copied from `deploy/pi.env.example`; default install dir `~/apps/overland-planner`) as
compose project `overland`. Every Pi target acts only on project `overland`, the `overland_*` volumes and the
`ghcr.io/mrmilgauss/overland-planner` images; none ever runs a docker prune or touches another stack (D99).

| Target | What it does |
|---|---|
| `make pi-preflight` | Read-only: port 8080 on the Pi's home-network address free (or ours), disk, MemAvailable, compose projects, `.env` with `PLANNER_BIND`; warns if a ghcr.io login is stored (D196 expects none). Prints no secret. |
| `make deploy [SHA=]` | Deploys a CI-green main SHA (provenance-checked); loopback smoke first, then the LAN publish; rolls back by itself on failure. |
| `make rollback [STEPS=1\|2]` | Back to `release.env.prev` (or `.prev2`); the image is already on the Pi. |
| `make status` / `make logs [SVC=planner]` / `make diag` | Read-only: compose ps, serving digest, `/healthz`, `/api/health`; the JSON log; `docker stats --no-stream` and `/healthz`. |
| `make image-gc` | Removes planner images except the three digests of `release.env`, `.prev` and `.prev2` (what rollback needs). |
| `make uninstall` | `docker compose down`: containers and network go, the data volume and files stay. |
| `make purge` | Asks you to type `purge overland`; then removes the containers, every `overland_*` volume (all trip data) and the planner images. No backup is taken. |
| `make dora` | Deployment frequency, lead time, change failure rate and time to restore from `.data/ops/releases.log` (copied back by every deploy and rollback). |

Before the first deploy (D178): give the Pi a DHCP reservation for its home-network address on the router (the planner
binds only that address).

Registry access (D196): the Pi stores no GHCR credential. `make deploy` reads the Mac's token with `gh auth token`
(it needs `read:packages`: `gh auth refresh -h github.com -s read:packages`) and pipes it over the ssh stdin to
`scripts/deploy.sh`, which runs `docker login ghcr.io -u MrMilgauss --password-stdin`, pulls the digest and runs
`docker logout ghcr.io` on every exit path. The token never appears on a command line, in a file or in the output.
If an older stored ghcr.io login is still on the Pi, `make pi-preflight` warns; remove it with `docker logout ghcr.io`
on the Pi.

**Accepted risk: no backups (D91).** The trip data lives only in the `overland_planner-data` volume on the Pi's NVMe.
Losing the device or the disk loses the data; the only copies are the short-lived predeploy/prerollback snapshots
next to it (the newest two of each), which exist for rollback, not for recovery. This is stated to Marco at the demo.

**Rolling back past schema 0005 deletes the plan runs.** Downgrading 0005 deletes all plan runs; projects and items
stay. A release at 0004 refuses a database at 0005 (`db_newer_than_app`), so going back to such a release needs the
snapshot and `alembic downgrade 0004` first. `make rollback` does both when the two images' schema heads differ; by
hand, follow the steps below with `0004` as `<head>`.

**Manual schema downgrade: snapshot first.** `make rollback` snapshots the volume before it runs `alembic downgrade`.
Running the downgrade by hand (`docker compose run --rm planner alembic downgrade <head>`, D90) takes no snapshot,
and a downgrade can commit part of its work before it fails (0004 commits mid-migration to switch
`PRAGMA foreign_keys`), so a failure can leave the database half downgraded. Take the snapshot `make rollback` would
take first, on the Pi in `~/apps/overland-planner` (add `--env-file routing.env` if that file exists):

```bash
docker compose -p overland --env-file .env --env-file release.env stop planner
mkdir -p snapshots
docker run --rm --network none -v overland_planner-data:/data:ro -v "$PWD/snapshots:/backup" \
  alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f \
  tar czf "/backup/prerollback-$(date -u +%Y%m%dT%H%M%SZ).tgz" -C /data .
docker compose -p overland --env-file .env --env-file release.env run --rm planner alembic downgrade <head>
```

If the downgrade fails, restore that file into the volume (the image and mounts of `restore_snapshot` in
`deploy/scripts/lib.sh`) before starting the planner again.

Idle memory on the Pi: **67.3 MiB** (measured 2026-11-03 18:53 UTC, release `88d53e8`, `docker stats`, CPU 0.13%) (planner only, after 10 minutes idle; limit 300 MB, KPI G1).

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
make e2e-local   # Playwright home-page check (chromium, webkit-iphone14) against run-local
make mutate      # mutmut on domain/application files changed since origin/main (kill rate >= 80 %)
```

Acceptance scenarios tagged `@pending` run with `--run-pending=<slice>`; `@requires_external` ones with
`--run-external` on the right host.

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
| Compressed image size, amd64 | _TBD (orchestrator)_ |
| Compressed image size, arm64 | _TBD (orchestrator)_ |
| Actions minutes per main push | _TBD (orchestrator)_ |

## Operations (pi-host)

The planner runs on Marco's Raspberry Pi 5 (`deploy@pi.example`, install dir `~/apps/overland-planner`) as
compose project `overland`. Every Pi target acts only on project `overland`, the `overland_*` volumes and the
`ghcr.io/mrmilgauss/overland-planner` images; none ever runs a docker prune or touches another stack (D99).

| Target | What it does |
|---|---|
| `make pi-preflight` | Read-only: port 8080 on 192.168.1.10 free (or ours), disk, MemAvailable, compose projects, `.env` with `PLANNER_BIND`; warns if a ghcr.io login is stored (D196 expects none). Prints no secret. |
| `make deploy [SHA=]` | Deploys a CI-green main SHA (provenance-checked); loopback smoke first, then the LAN publish; rolls back by itself on failure. |
| `make rollback [STEPS=1\|2]` | Back to `release.env.prev` (or `.prev2`); the image is already on the Pi. |
| `make status` / `make logs [SVC=planner]` / `make diag` | Read-only: compose ps, serving digest, `/healthz`, `/api/health`; the JSON log; `docker stats --no-stream` and `/healthz`. |
| `make image-gc` | Removes planner images except the three digests of `release.env`, `.prev` and `.prev2` (what rollback needs). |
| `make uninstall` | `docker compose down`: containers and network go, the data volume and files stay. |
| `make purge` | Asks you to type `purge overland`; then removes the containers, every `overland_*` volume (all trip data) and the planner images. No backup is taken. |
| `make dora` | Deployment frequency, lead time, change failure rate and time to restore from `.data/ops/releases.log` (copied back by every deploy and rollback). |

Before the first deploy (D178): give pi-host a DHCP reservation for 192.168.1.10 on the home router (the planner
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

Idle memory on pi-host: <to be measured> (planner only, after 10 minutes idle; limit 300 MB, KPI G1).

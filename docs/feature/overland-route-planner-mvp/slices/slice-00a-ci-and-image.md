# Slice 00a (enabler): CI and a published planner image

Priority: 0a | Type: enabler (technical tasks, no user story; D145, OD-1) | Enables: US-01a (all scenarios), the walking skeleton in CI | job_id: infrastructure-only | infrastructure_rationale: every user slice must reach the Pi as a CI-green, attested image; without this pipeline slice 00b cannot deploy and no later slice can be demoed

## Goal

Every push gets lint, tests and the web build in CI; every green `main` push publishes one multi-arch planner image (amd64 + arm64) that slice 00b can deploy by digest.

## IN (DEVOPS D84-D88, D98, D102; fixes F-01..F-03, F-10, F-12, F-14, F-15)

- `pre-commit` / pre-push gates; Makefile `bootstrap`, `lint`, `test`, `test-web`, `run-local`
- `ci.yml` jobs: lint; test-python (runs the web build itself, `npm ci && vite build`, so the walking skeleton checks the real built page, UD-1); test-web; image-amd64; image-arm64 (QEMU by default) with functional smoke; publish (manifest list, attestations, `release.json`) gated on `main`
- Multi-stage Dockerfile, non-root, pinned bases; Trivy (vuln + secret) on both arches; dependency audit
- Optional jobs (golden order, mutation) are added to `needs` and to the publish `if:` expression only by the slice that creates them (D160)
- DEVOPS-owned `PENDING_FLAGS` list (workflow `env`) passed to pytest in jobs 2 and 7, today `--run-pending=slice-00b --run-pending=slice-01a`; extended in the commit that turns a slice's scenarios GREEN, so they are blocking from then on (D170, re-review N-01)
- GHCR keeps only the latest release (job 9 prunes; referenced per-arch children kept); e2e image artifact deleted after load; measure the compressed image size per arch and record it against the 500 MB storage budget (D169, N-02)

## OUT

- Compose stack on the Pi, deploy/rollback, basic auth, LAN-only (slice 00b); golden order (03-ops); Valhalla (06a-ops)

## Learning hypothesis

Disproves "a free-plan GitHub pipeline can build and smoke-test an arm64 planner image within the runner-minute budget" if the QEMU arm64 job fails or the main pipeline exceeds about 45 runner-minutes (D169).

## Done when

- A `main` push yields a manifest-list digest with amd64 + arm64, attestation verifiable with `gh attestation verify`; the arm64 smoke shows `/healthz` ok and the solver probe ok
- The walking skeleton scenario runs in job 2 against the built page (RED until slice 01a)
- Unblocks: US-01a "The same setup runs on Marco's PC", "Sharing the planner image never shares Marco's secrets"

## Demo

No separate demo: shown with slice 00b (Marco deploys the digest this slice published).

## Dependencies

DEVOPS pre-requisites 1-4 (private repo, GHCR owner name, PAT, `gh auth`).

## Effort and reference class

1.0 day. Reference class: greenfield GitHub Actions + buildx multi-arch pipeline.

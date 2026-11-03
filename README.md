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
image jobs (amd64, arm64), e2e on the amd64 image, scoped mutation testing and publish. Publish creates the attested
manifest list `ghcr.io/mrmilgauss/overland-planner:sha-<12>` and `:main`, uploads `release.json` and prunes GHCR to
that release. `.github/workflows/weekly.yml` re-scans `main`, audits dependencies, runs the deep property profile and
reports storage; deploys never wait for it.

### CI budget

| Item | Value |
| --- | --- |
| Compressed image size, amd64 | _TBD (orchestrator)_ |
| Compressed image size, arm64 | _TBD (orchestrator)_ |
| Actions minutes per main push | _TBD (orchestrator)_ |

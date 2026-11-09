# Developer entry points (Mac and Pi).
.PHONY: bootstrap lint lint-ci test test-web web-dist mutate openapi-snapshot run-local e2e-local deploy rollback \
	pi-preflight status logs diag image-gc uninstall purge dora perf-pi

PYTEST_FAST := -m "not slow and not solver_child"
# The production command (Dockerfile at 01-06 uses the same factory; stdout carries only JSON event lines because the
# composition root switches off uvicorn's access log).
UVICORN := uv run uvicorn --factory overland_planner.bootstrap.app_factory:create_app
HOST ?= 127.0.0.1
PORT ?= 8080
BASE ?= origin/main
MUTATE_SCOPE := src/overland_planner/domain src/overland_planner/application
KILL_RATE_MIN := 80
# Fallback when actionlint/shellcheck are not on PATH: the PyPI wheels that ship the same release binaries.
ACTIONLINT_PY := actionlint-py==1.7.12.24
SHELLCHECK_PY := shellcheck-py==0.11.0.1
SHELL_SCRIPTS := .github/scripts/*.sh deploy/scripts/*.sh
# make deploy target (D89); override for another host.
PI_HOST ?= deploy@pi.example
PI_DIR ?= apps/overland-planner
SHA ?=
STEPS ?= 1
SVC ?= planner
RELEASES_LOG ?= .data/ops/releases.log
# shellcheck severity of every local and CI run (make lint-ci, pre-commit, CI job 1): all findings down to info.
SHELLCHECK_SEVERITY := info
# Pi operations (D99): only compose project `overland`, volumes overland_*, images of PLANNER_REPO; never a prune.
# The remote shell is the deploy user's login shell on pi-host (bash); scripts/lib.sh is there since the first deploy.
PLANNER_REPO := ghcr.io/mrmilgauss/overland-planner
PI_SSH = ssh -o BatchMode=yes $(PI_HOST)
PI_COMPOSE := docker compose -p overland --env-file .env --env-file release.env
PURGE_WORD := purge overland
# make perf-pi (D96, D146, D135): N measured runs of ITEMS items; POINTS (points per track) empty = the committed 12.
N ?= 10
ITEMS ?= 60
POINTS ?=

bootstrap: ## Install locked Python dependencies and the pre-commit + pre-push hooks
	uv sync --locked
	uv run pre-commit install --install-hooks

lint: ## ruff, mypy --strict on src, import-linter (brief section 11)
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run lint-imports

lint-ci: ## actionlint + shellcheck on the workflows and shellcheck on .github/scripts and deploy/scripts (as CI job 1 lint)
	@if command -v actionlint >/dev/null && command -v shellcheck >/dev/null; then \
	  echo "lint-ci: using $$(command -v actionlint) and $$(command -v shellcheck)"; \
	  actionlint -shellcheck "$$(command -v shellcheck)" .github/workflows/*.yml && \
	  shellcheck --severity=$(SHELLCHECK_SEVERITY) $(SHELL_SCRIPTS); \
	elif command -v uvx >/dev/null; then \
	  echo "lint-ci: actionlint and/or shellcheck not on PATH; using uvx $(ACTIONLINT_PY) and $(SHELLCHECK_PY)"; \
	  uvx --from $(SHELLCHECK_PY) shellcheck --severity=$(SHELLCHECK_SEVERITY) $(SHELL_SCRIPTS) && \
	  uvx --from $(ACTIONLINT_PY) --with $(SHELLCHECK_PY) actionlint .github/workflows/*.yml; \
	else \
	  echo "lint-ci: FAILED - actionlint and shellcheck are not installed (and uvx is missing);" \
	    "without shellcheck actionlint skips the run: scripts, so CI findings would be missed" >&2; \
	  exit 1; \
	fi

test: web-dist ## Fast suite (same selection as pre-push); builds the web page first (D162 home-page tests)
	uv run pytest -q $(PYTEST_FAST)

web-dist: ## Build web/dist with vite (installs the locked node modules when missing)
	cd web && if [ ! -d node_modules ]; then npm ci --no-audit --no-fund; fi
	cd web && npx vite build

test-web: ## Reproducible web build from package-lock.json: npm ci, svelte-check, vitest, vite build -> web/dist
	cd web && npm ci --no-audit --no-fund
	cd web && npm run check
	cd web && npx vitest run
	cd web && npx vite build

openapi-snapshot: ## Regenerate tests/contract/http/openapi.json on purpose after an API change (commit it with the change)
	uv run python -m tests.contract.http.test_openapi_snapshot

run-local: web-dist ## The planner on http://$(HOST):$(PORT) with ./.data/dev and the offline mock road map
	mkdir -p .data/dev
	DATA_DIR=./.data/dev ROUTING_PROVIDER=mock $(UVICORN) --host $(HOST) --port $(PORT)

mutate: web-dist ## mutmut on domain/application files changed since BASE (default origin/main; BASE=all: every file); fails below 80 % kill rate; files without mutants (e.g. only a Protocol) pass
	@if [ "$(BASE)" = all ]; then files="$$(git ls-files -- $(MUTATE_SCOPE) | grep '\.py$$')"; \
	else files="$$(git diff --name-only --diff-filter=d $$(git merge-base $(BASE) HEAD) -- $(MUTATE_SCOPE) | grep '\.py$$')"; fi; \
	if [ -z "$$files" ]; then echo "mutate: no domain/application file changed since $(BASE)"; exit 0; fi; \
	globs="$$(echo "$$files" | sed -e 's|^src/||' -e 's|\.py$$||' -e 's|/__init__$$||' -e 's|/|.|g' -e 's|$$|.*|')"; \
	echo "mutate: $$(echo $$files)"; \
	rm -rf mutants; \
	log="$$(mktemp)"; \
	{ HYPOTHESIS_PROFILE=mutation uv run mutmut run $$globs 2>&1; echo "$$?" > "$$log.status"; } | tee "$$log"; \
	status="$$(cat "$$log.status")"; \
	if [ "$$status" != 0 ] && grep -q "Filtered for specific mutants, but nothing matches" "$$log"; then \
	  rm -f "$$log" "$$log.status"; echo "mutate: no mutants in scope"; exit 0; fi; \
	rm -f "$$log" "$$log.status"; \
	[ "$$status" = 0 ] || exit 1; \
	uv run mutmut export-cicd-stats >/dev/null || exit 1; \
	uv run python -c 'import json, sys; s = json.load(open("mutants/mutmut-cicd-stats.json")); \
	caught = s["killed"] + s["timeout"]; scored = caught + s["survived"] + s["no_tests"]; \
	scored or (print("mutate: no mutants in scope"), sys.exit(0)); \
	rate = 100.0 * caught / scored; \
	print(f"mutate: kill rate {rate:.1f}% ({caught}/{scored}); minimum $(KILL_RATE_MIN)%"); \
	sys.exit(0 if rate >= $(KILL_RATE_MIN) else 1)'

e2e-local: ## Playwright home-page check (chromium, webkit-iphone14) against `make run-local`, started for the run
	cd web && if [ ! -d node_modules ]; then npm ci --no-audit --no-fund; fi
	cd web && npx --no-install playwright install chromium webkit
	cd web && NODE_PATH="$$PWD/node_modules" E2E_START_LOCAL=1 PLANNER_URL=http://$(HOST):$(PORT) npx --no-install playwright test --project=chromium --project=webkit-iphone14

deploy: ## Deploy a CI-green main SHA to the Pi (default: newest with release.json); provenance-checked, loopback-first, auto-rollback
	PI_HOST=$(PI_HOST) bash deploy/scripts/make-deploy.sh $(SHA)

rollback: ## Roll the Pi back to release.env.prev (STEPS=2: .prev2); image already on the Pi, so no provenance check (D195)
	@case "$(STEPS)" in 1|2) ;; *) echo "make rollback: STEPS must be 1 or 2" >&2; exit 2 ;; esac; \
	status=0; \
	ssh -o BatchMode=yes $(PI_HOST) 'cd $(PI_DIR) && bash scripts/rollback.sh $(STEPS)' || status=$$?; \
	mkdir -p .data/ops; \
	if rsync -a $(PI_HOST):$(PI_DIR)/releases.log .data/ops/releases.log; then tail -n 3 .data/ops/releases.log; \
	else echo "make rollback: could not copy releases.log back" >&2; fi; \
	if [ $$status -ne 0 ]; then echo "make rollback: rollback failed on the Pi (exit $$status); see releases.log" >&2; exit 1; fi

pi-preflight: ## Read-only Pi check before the first deploy: port 8080 free or ours, disk, MemAvailable, compose projects, .env, ghcr login
	$(PI_SSH) 'bash -s -- $(PI_DIR)' < deploy/scripts/pi-preflight.sh

status: ## compose ps of project overland, the serving digest, /healthz and /api/health (read-only)
	$(PI_SSH) 'cd $(PI_DIR) && $(PI_COMPOSE) ps && grep "^PLANNER_IMAGE=" release.env && . scripts/lib.sh && \
	  url="http://$$(env_value .env PLANNER_BIND):$$(planner_port)" && curl -fsS --max-time 10 "$$url/healthz" && echo && \
	  curl_planner "$$url/api/health" && echo'

logs: ## Follow the JSON log of SVC (default planner), pretty-printed with jq when the Mac has it (read-only)
	$(PI_SSH) 'cd $(PI_DIR) && $(PI_COMPOSE) logs -f --no-log-prefix $(SVC)' | \
	  if command -v jq >/dev/null; then jq -R 'fromjson? // .'; else cat; fi

diag: ## Container stats of project overland (no stream), /healthz and /api/diagnostics read with the Pi's .env password (never printed); jq pretty-prints on the Mac when present (read-only)
	@out=$$($(PI_SSH) 'cd $(PI_DIR) && docker stats --no-stream $$($(PI_COMPOSE) ps -q) && . scripts/lib.sh && \
	  url="http://$$(env_value .env PLANNER_BIND):$$(planner_port)" && curl -fsS --max-time 10 "$$url/healthz" && echo && \
	  curl_planner "$$url/api/diagnostics" && echo') || exit $$?; \
	printf '%s\n' "$$out" | if command -v jq >/dev/null; then jq -R -r 'fromjson? // .'; else cat; fi

image-gc: ## Remove planner images except the three digests of release.env, .prev and .prev2 (rollback needs them)
	$(PI_SSH) 'cd $(PI_DIR) && keep="$$(sed -n "s|^PLANNER_IMAGE=.*@||p" release.env release.env.prev release.env.prev2 2>/dev/null)" && \
	  docker image ls --digests --format "{{.Repository}}@{{.Digest}}" $(PLANNER_REPO) | while read -r ref; do \
	    case "$${ref#*@}" in "<none>"|"") continue ;; esac; \
	    case " $$(echo $$keep) " in *" $${ref#*@} "*) echo "image-gc: keeping $$ref" ;; \
	      *) docker image rm "$$ref" || echo "image-gc: $$ref still in use, kept" ;; esac; \
	  done'

uninstall: ## Stop and remove the overland containers and network; the data volume and the files stay
	$(PI_SSH) 'cd $(PI_DIR) && $(PI_COMPOSE) down'

purge: ## Remove project overland with its overland_* volumes and planner images (typed confirmation; NO backup is taken)
	@printf '%s\n' "make purge removes the overland containers, every overland_* volume (ALL trip data) and the" \
	  "$(PLANNER_REPO) images on $(PI_HOST). No backup is taken (D91). Type '$(PURGE_WORD)' to go on:"; \
	read -r answer || answer=; \
	if [ "$$answer" != "$(PURGE_WORD)" ]; then echo "make purge: aborted, nothing removed" >&2; exit 1; fi; \
	$(PI_SSH) 'cd $(PI_DIR) && $(PI_COMPOSE) down && \
	  docker volume ls -q | while read -r volume; do case "$$volume" in overland_*) docker volume rm "$$volume" ;; esac; done && \
	  docker image ls --digests --format "{{.Repository}}@{{.Digest}}" $(PLANNER_REPO) | while read -r ref; do \
	    case "$${ref#*@}" in "<none>"|"") ;; *) docker image rm "$$ref" ;; esac; \
	  done'

perf-pi: ## K5 on planner-perf (deployed digest; deploy first): golden I1 + I2, warm-up, N runs (N=10 ITEMS=60 gate; POINTS=20000 guard gate); report in .data/perf/. Run by the orchestrator at a start time the user names, never by the crafter
	PI_HOST=$(PI_HOST) PI_DIR=$(PI_DIR) N=$(N) ITEMS=$(ITEMS) POINTS=$(POINTS) bash deploy/scripts/perf-pi.sh

dora: ## DORA metrics (deployment frequency, lead time, change failure rate, time to restore) from RELEASES_LOG
	uv run python deploy/scripts/dora.py $(RELEASES_LOG)

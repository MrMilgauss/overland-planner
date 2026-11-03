# Developer entry points (Mac and Pi).
.PHONY: bootstrap lint test test-web web-dist mutate run-local e2e-local

PYTEST_FAST := -m "not slow and not solver_child and not walking_skeleton"
# The production command (Dockerfile at 01-06 uses the same factory; stdout carries only JSON event lines because the
# composition root switches off uvicorn's access log).
UVICORN := uv run uvicorn --factory overland_planner.bootstrap.app_factory:create_app
HOST ?= 127.0.0.1
PORT ?= 8080
BASE ?= origin/main
MUTATE_SCOPE := src/overland_planner/domain src/overland_planner/application
KILL_RATE_MIN := 80

bootstrap: ## Install locked Python dependencies and the pre-commit + pre-push hooks
	uv sync --locked
	uv run pre-commit install --install-hooks

lint: ## ruff, mypy --strict on src, import-linter (brief section 11)
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run lint-imports

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

run-local: web-dist ## The planner on http://$(HOST):$(PORT) with ./.data/dev and the offline mock road map
	mkdir -p .data/dev
	DATA_DIR=./.data/dev ROUTING_PROVIDER=mock $(UVICORN) --host $(HOST) --port $(PORT)

mutate: web-dist ## mutmut on domain/application files changed since BASE (default origin/main; BASE=all: every file); fails below 80 % kill rate
	@if [ "$(BASE)" = all ]; then files="$$(git ls-files -- $(MUTATE_SCOPE) | grep '\.py$$')"; \
	else files="$$(git diff --name-only --diff-filter=d $$(git merge-base $(BASE) HEAD) -- $(MUTATE_SCOPE) | grep '\.py$$')"; fi; \
	if [ -z "$$files" ]; then echo "mutate: no domain/application file changed since $(BASE)"; exit 0; fi; \
	globs="$$(echo "$$files" | sed -e 's|^src/||' -e 's|\.py$$||' -e 's|/__init__$$||' -e 's|/|.|g' -e 's|$$|.*|')"; \
	echo "mutate: $$(echo $$files)"; \
	rm -rf mutants; \
	HYPOTHESIS_PROFILE=mutation uv run mutmut run $$globs || exit 1; \
	uv run mutmut export-cicd-stats >/dev/null || exit 1; \
	uv run python -c 'import json, sys; s = json.load(open("mutants/mutmut-cicd-stats.json")); \
	caught = s["killed"] + s["timeout"]; scored = caught + s["survived"] + s["no_tests"]; \
	rate = 100.0 * caught / scored if scored else 100.0; \
	print(f"mutate: kill rate {rate:.1f}% ({caught}/{scored}); minimum $(KILL_RATE_MIN)%"); \
	sys.exit(0 if rate >= $(KILL_RATE_MIN) else 1)'

e2e-local: ## Playwright home-page check (chromium, webkit-iphone14) against `make run-local`, started for the run
	cd web && if [ ! -d node_modules ]; then npm ci --no-audit --no-fund; fi
	cd web && npx --no-install playwright install chromium webkit
	cd web && NODE_PATH="$$PWD/node_modules" E2E_START_LOCAL=1 PLANNER_URL=http://$(HOST):$(PORT) npx --no-install playwright test

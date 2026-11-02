# Developer entry points (Mac and Pi). run-local and mutate arrive at 01-04.
.PHONY: bootstrap lint test test-web

PYTEST_FAST := -m "not slow and not solver_child and not walking_skeleton"

bootstrap: ## Install locked Python dependencies and the pre-commit + pre-push hooks
	uv sync --locked
	uv run pre-commit install --install-hooks

lint: ## ruff, mypy --strict on src, import-linter (brief section 11)
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run lint-imports

test: ## Fast suite (same selection as pre-push)
	uv run pytest -q $(PYTEST_FAST)

test-web: ## Reproducible web build from package-lock.json: npm ci, svelte-check, vitest, vite build -> web/dist
	cd web && npm ci --no-audit --no-fund
	cd web && npm run check
	cd web && npx vitest run
	cd web && npx vite build

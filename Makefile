# Developer entry points (Mac and Pi). test-web arrives at 01-02; run-local and mutate at 01-04.
.PHONY: bootstrap lint test

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

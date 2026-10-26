.DEFAULT_GOAL := help
SHELL := /bin/bash
UV := uv run

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install dependencies and git hooks
	uv sync --all-groups
	$(UV) pre-commit install

.PHONY: up
up: ## Start the stack (PROFILES=bi adds Metabase)
	@test -f .env || (echo "Missing .env - run: cp .env.example .env" && exit 1)
	docker compose $(foreach p,$(PROFILES),--profile $(p)) up -d --build

.PHONY: down
down: ## Stop the stack (data volumes are kept)
	docker compose --profile bi down

.PHONY: lint
lint: ## ruff, mypy, sqlfluff
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) mypy src
	$(UV) sqlfluff lint src/power_market/sql

.PHONY: format
format: ## Format Python code
	$(UV) ruff check --fix .
	$(UV) ruff format .

.PHONY: test
test: ## Unit and integration tests with coverage
	$(UV) pytest

.PHONY: test-unit
test-unit: ## Unit tests only (no Docker needed)
	$(UV) pytest -m "not integration" --cov-fail-under=0

.PHONY: run
run: ## One incremental run from the CLI
	$(UV) python -m power_market run

.PHONY: backfill
backfill: ## Load a date range: make backfill START=2023-01-01 [END=2023-12-31]
	@test -n "$(START)" || (echo "Usage: make backfill START=YYYY-MM-DD [END=YYYY-MM-DD]" && exit 1)
	$(UV) python -m power_market backfill --start $(START) $(if $(END),--end $(END))

.PHONY: clean
clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml dist build
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +

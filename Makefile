.DEFAULT_GOAL := help
SHELL := /bin/bash
UV := uv run
TARGET ?= dev
DBT_ARGS ?=
# dbt reads the connection from the environment; load .env when it exists
DBT := set -a; [ -f .env ] && . ./.env; set +a; cd dbt && DBT_PROFILES_DIR=. DBT_TARGET=$(TARGET) uv run dbt

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
	$(UV) sqlfluff lint src/power_market/sql dbt metabase/questions

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

.PHONY: dag-check
dag-check: ## Build the Airflow image and check the DAG inside it
	docker build -q -f airflow/Dockerfile -t power-market-airflow:check .
	docker run --rm --entrypoint python power-market-airflow:check /opt/airflow/tests/check_dags.py

.PHONY: dbt-build
dbt-build: ## Seed, run and test the dbt project (TARGET=dev|prod)
	$(DBT) deps
	$(DBT) build $(DBT_ARGS)

.PHONY: dbt-freshness
dbt-freshness: ## Check source freshness
	$(DBT) deps
	$(DBT) source freshness

.PHONY: dbt-docs
dbt-docs: ## Data dictionary on http://localhost:8081
	$(DBT) deps
	$(DBT) docs generate && $(DBT) docs serve --port 8081

.PHONY: sample-data
sample-data: ## Replace raw.* with the committed sample week (used by CI)
	$(UV) python scripts/load_sample_data.py

.PHONY: clean
clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml dist build
	rm -rf dbt/target dbt/logs dbt/dbt_packages
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +

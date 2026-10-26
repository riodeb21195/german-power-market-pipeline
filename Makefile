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

.PHONY: lint
lint: ## ruff, mypy, sqlfluff
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) mypy src

.PHONY: format
format: ## Format Python code
	$(UV) ruff check --fix .
	$(UV) ruff format .

.PHONY: test
test: ## Unit and integration tests with coverage
	$(UV) pytest

.PHONY: clean
clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml dist build
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +

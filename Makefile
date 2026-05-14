.PHONY: help install install-dev migrate lint test test-unit test-integration bootstrap-taxonomy vault-open clean

PYTHON ?= python3
SG ?= sg

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

install: ## Install the package and all dependencies
	$(PYTHON) -m pip install -e .
	$(PYTHON) -m playwright install chromium --with-deps

install-dev: install ## Install dev dependencies too
	$(PYTHON) -m pip install -e ".[dev]"

migrate: ## Run Alembic migrations (create DB + tables)
	alembic upgrade head

lint: ## Run ruff linter and formatter check
	ruff check socialgraph tests
	ruff format --check socialgraph tests

format: ## Auto-format with ruff
	ruff format socialgraph tests
	ruff check --fix socialgraph tests

test: ## Run all tests
	pytest tests/ -v

test-unit: ## Run unit tests only
	pytest tests/unit/ -v

test-integration: ## Run integration tests (requires .env)
	pytest tests/integration/ -v

test-e2e: ## Run end-to-end pipeline test
	pytest tests/e2e/ -v -s

bootstrap-taxonomy: ## Build initial topic taxonomy from sampled posts
	$(PYTHON) scripts/bootstrap_taxonomy.py

vault-open: ## Open Obsidian vault (requires Obsidian installed)
	xdg-open vault/ 2>/dev/null || open vault/ 2>/dev/null || echo "Open vault/ in Obsidian manually"

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .ruff_cache .mypy_cache .pytest_cache dist

# Pipeline shortcuts
ingest: ## Ingest posts from linkedin_saved_posts.json
	$(SG) ingest --json linkedin_saved_posts.json

enrich: ## Enrich all pending posts (fetch external URLs + comments)
	$(SG) enrich

classify: ## Classify posts into topics
	$(SG) classify

build-graph: ## Build the knowledge graph
	$(SG) build-graph

vault-write: ## Write Obsidian vault from graph
	$(SG) vault-write

run: ## Run the full pipeline end-to-end
	$(SG) run

status: ## Show pipeline status
	$(SG) status

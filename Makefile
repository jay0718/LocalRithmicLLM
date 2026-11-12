.DEFAULT_GOAL := help
.PHONY: help dev web web-check test test-integration lint format guard demo up down smoke

help: ## List available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "%-10s %s\n", $$1, $$2}'

dev: ## Install all packages and dev tools
	uv sync

web: ## Run the UI dev server on http://127.0.0.1:5173
	cd web && npm run dev -- --host 127.0.0.1

web-check: ## Type check, lint, test and build the UI
	cd web && npm run api:check && npm run typecheck && npm run lint && npm test && npm run build

test: ## Run all tests with coverage
	uv run pytest

test-integration: ## Run tests against the running Compose stack
	LRL_INTEGRATION=1 uv run pytest -m integration --no-cov

lint: ## Check style and imports
	uv run ruff check .
	uv run ruff format --check .

format: ## Apply style and import fixes
	uv run ruff check --fix .
	uv run ruff format .

guard: ## Fail if secrets or Rithmic kit files are tracked
	python3 scripts/check_tracked_files.py

demo: ## Run the credential-free replay demo
	uv run python scripts/demo.py

up: ## Start the infrastructure stack and wait until healthy
	docker compose up -d --wait

down: ## Stop the stack, keeping data volumes
	docker compose down

smoke: ## Check every service in the running stack
	./scripts/smoke_compose.sh

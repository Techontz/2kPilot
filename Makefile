# Common developer commands. Run `make help`.
BACKEND := backend
FRONTEND := frontend
VENV := $(BACKEND)/.venv/bin

.PHONY: help setup migrate backend frontend test lint check build

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup: ## Create venv, install all dependencies
	python3.11 -m venv $(BACKEND)/.venv
	$(VENV)/pip install -e "$(BACKEND)[dev]"
	cd $(FRONTEND) && npm install

migrate: ## Apply database migrations
	cd $(BACKEND) && .venv/bin/alembic upgrade head

backend: ## Run the API (http://127.0.0.1:8000, docs at /api/docs)
	cd $(BACKEND) && .venv/bin/uvicorn fxrobot.main:create_app --factory --reload --no-proxy-headers --host 127.0.0.1 --port 8000

frontend: ## Run the dashboard (http://localhost:3000)
	cd $(FRONTEND) && npm run dev

test: ## Run backend and frontend tests
	cd $(BACKEND) && .venv/bin/pytest
	cd $(FRONTEND) && npm test

lint: ## Lint and type-check everything
	cd $(BACKEND) && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/mypy
	cd $(FRONTEND) && npm run lint && npm run typecheck

check: lint test ## Everything CI should run
	cd $(BACKEND) && .venv/bin/alembic check

build: ## Production frontend build
	cd $(FRONTEND) && npm run build

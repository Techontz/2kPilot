# 2kFX ROBOT — developer commands. Run `make help`.
#
# Ports are configurable, e.g.:  make dev BACKEND_PORT=8421 FRONTEND_PORT=3421
BACKEND := backend
FRONTEND := frontend
BRIDGE := mt5_bridge
VENV := $(BACKEND)/.venv/bin
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 3000
PYTHON ?= python3.11

.PHONY: help setup env db migrate user dev backend frontend test test-backend test-frontend \
        bridge-test e2e lint check build clean-e2e

help:
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup: ## First-time install: Python venv, npm packages, backend/.env with a new encryption key
	$(PYTHON) -m venv $(BACKEND)/.venv
	$(VENV)/pip install -q --upgrade pip
	$(VENV)/pip install -q -e "$(BACKEND)[dev]"
	cd $(FRONTEND) && npm install
	cd $(BACKEND) && .venv/bin/python scripts/init_env.py
	@echo "Next: edit DATABASE_URL in backend/.env if needed, then: make db && make user && make dev"

env: ## Create backend/.env (never overwrites) — optional: make env DB=mysql+pymysql://...
	cd $(BACKEND) && .venv/bin/python scripts/init_env.py $(DB)

db: ## Create the MySQL database (if missing) and apply all migrations
	cd $(BACKEND) && .venv/bin/python scripts/create_db.py && .venv/bin/alembic upgrade head

migrate: ## Apply database migrations
	cd $(BACKEND) && .venv/bin/alembic upgrade head

user: ## Create your login: make user EMAIL=you@example.com NAME=Conrad (prompts for password)
	@test -n "$(EMAIL)" || (echo "Usage: make user EMAIL=you@example.com NAME=Conrad" && exit 1)
	cd $(BACKEND) && .venv/bin/fxrobot create-user --email "$(EMAIL)" --name "$(or $(NAME),Conrad)"

dev: ## Run backend (API + trading engine) and frontend together; Ctrl+C stops both
	@echo "Dashboard: http://localhost:$(FRONTEND_PORT)   API docs: http://127.0.0.1:$(BACKEND_PORT)/api/docs"
	@trap 'kill 0' INT TERM EXIT; \
	(cd $(BACKEND) && .venv/bin/uvicorn fxrobot.main:create_app --factory --no-proxy-headers --host 127.0.0.1 --port $(BACKEND_PORT)) & \
	(cd $(FRONTEND) && BACKEND_URL=http://127.0.0.1:$(BACKEND_PORT) npx next dev -p $(FRONTEND_PORT)) & \
	wait

backend: ## Run only the API + trading engine (auto-reload)
	cd $(BACKEND) && .venv/bin/uvicorn fxrobot.main:create_app --factory --reload --no-proxy-headers --host 127.0.0.1 --port $(BACKEND_PORT)

frontend: ## Run only the dashboard (dev server)
	cd $(FRONTEND) && BACKEND_URL=http://127.0.0.1:$(BACKEND_PORT) npx next dev -p $(FRONTEND_PORT)

test: test-backend test-frontend ## Backend + frontend unit/integration tests

test-backend: ## Backend tests against MySQL (TEST_DATABASE_URL, default fxrobot_test on :3308)
	cd $(BACKEND) && .venv/bin/pytest

test-frontend: ## Frontend unit tests (Vitest)
	cd $(FRONTEND) && npm test

bridge-test: ## MT5 bridge tests (fake MT5 module; runs on macOS/Linux)
	cd $(BRIDGE) && test -d .venv || $(PYTHON) -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
	cd $(BRIDGE) && .venv/bin/pytest -q && .venv/bin/ruff check src tests && .venv/bin/mypy

e2e: ## Browser end-to-end tests (real backend + production build, uses Google Chrome)
	cd $(FRONTEND) && npm run e2e

lint: ## Lint and type-check backend and frontend
	cd $(BACKEND) && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/mypy
	cd $(FRONTEND) && npm run lint && npm run typecheck

check: lint test ## Everything CI should run (plus migration drift check)
	cd $(BACKEND) && .venv/bin/alembic check

build: ## Production frontend build
	cd $(FRONTEND) && BACKEND_URL=http://127.0.0.1:$(BACKEND_PORT) npm run build

# 2kPilot — developer commands. Run `make help`.
#
#   frontend/        Next.js dashboard            (port FRONTEND_PORT, default 3421)
#   backend/         Laravel API + auth + queue   (port BACKEND_PORT,  default 8421)
#   trading-engine/  Python trading engine        (port ENGINE_PORT,   default 8431, internal only)
#   Redis (127.0.0.1:6379) runs the queues (Horizon) and the cache.
BACKEND := backend
ENGINE := trading-engine
FRONTEND := frontend
VENV := $(ENGINE)/.venv/bin
BACKEND_PORT ?= 8421
ENGINE_PORT ?= 8431
FRONTEND_PORT ?= 3421
PYTHON ?= python3.11

.PHONY: help setup db user dev engine backend frontend worker scheduler test test-backend test-engine \
        test-frontend e2e lint check build migrate-check

help:
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup: ## First-time install: PHP + Python + npm packages, env files, shared secrets
	cd $(BACKEND) && composer install && (test -f .env || cp .env.example .env) && php artisan key:generate --no-interaction
	$(PYTHON) -m venv $(ENGINE)/.venv
	$(VENV)/pip install -q --upgrade pip && $(VENV)/pip install -q -e "$(ENGINE)[dev]"
	test -f $(ENGINE)/.env || cp $(ENGINE)/.env.example $(ENGINE)/.env
	cd $(BACKEND) && php artisan tp:keys
	cd $(FRONTEND) && npm install
	@echo "Next: set DB_* in backend/.env and DATABASE_URL in trading-engine/.env, then: make db && make user && make dev"

db: ## Create the MySQL database tables (Laravel migrations)
	cd $(BACKEND) && php artisan migrate --force

user: ## Create a login: make user EMAIL=you@example.com NAME=Conrad [ROLE=admin] (prompts for a password)
	@test -n "$(EMAIL)" || (echo "Usage: make user EMAIL=you@example.com NAME=Conrad [ROLE=admin]" && exit 1)
	cd $(BACKEND) && php artisan tp:user --email="$(EMAIL)" --name="$(or $(NAME),User)" --role="$(or $(ROLE),user)"

dev: ## Run everything (engine, API, Horizon queues, scheduler, dashboard; needs Redis); Ctrl+C stops all
	@echo "Dashboard: http://localhost:$(FRONTEND_PORT)"
	@trap 'kill 0' INT TERM EXIT; \
	(cd $(ENGINE) && .venv/bin/fxrobot serve --port $(ENGINE_PORT)) & \
	(cd $(BACKEND) && PHP_CLI_SERVER_WORKERS=8 php artisan serve --no-reload --host=127.0.0.1 --port=$(BACKEND_PORT)) & \
	(cd $(BACKEND) && php artisan horizon --quiet) & \
	(cd $(BACKEND) && php artisan schedule:work --quiet) & \
	(cd $(FRONTEND) && BACKEND_URL=http://127.0.0.1:$(BACKEND_PORT) npx next dev -p $(FRONTEND_PORT)) & \
	wait

engine: ## Run only the trading engine
	cd $(ENGINE) && .venv/bin/fxrobot serve --port $(ENGINE_PORT)

backend: ## Run only the Laravel API
	cd $(BACKEND) && PHP_CLI_SERVER_WORKERS=8 php artisan serve --no-reload --host=127.0.0.1 --port=$(BACKEND_PORT)

worker: ## Run only the queue workers (Horizon: backtests, notifications; dashboard at /horizon for admins)
	cd $(BACKEND) && php artisan horizon

scheduler: ## Run only the Laravel scheduler (engine watchdog, daily summary, pruning)
	cd $(BACKEND) && php artisan schedule:work

frontend: ## Run only the dashboard (dev server)
	cd $(FRONTEND) && BACKEND_URL=http://127.0.0.1:$(BACKEND_PORT) npx next dev -p $(FRONTEND_PORT)

test: test-backend test-engine test-frontend ## All unit/integration tests

test-backend: ## Laravel tests (MySQL database tradepilot_test)
	cd $(BACKEND) && php artisan test

test-engine: ## Trading-engine tests (schema built by the Laravel migrations)
	cd $(ENGINE) && .venv/bin/pytest

test-frontend: ## Frontend unit tests (Vitest)
	cd $(FRONTEND) && npm test

e2e: ## Browser end-to-end tests (real Laravel + engine + MySQL + production build, Google Chrome)
	cd $(FRONTEND) && npx playwright test

lint: ## Lint and type-check everything
	cd $(BACKEND) && vendor/bin/pint --test
	cd $(ENGINE) && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/mypy
	cd $(FRONTEND) && npm run lint && npm run typecheck

migrate-check: ## Migrations from scratch, full rollback, and back up (database tradepilot_test)
	cd $(BACKEND) && DB_DATABASE=tradepilot_test php artisan migrate:fresh --force && DB_DATABASE=tradepilot_test php artisan migrate:rollback --force --step=100 && DB_DATABASE=tradepilot_test php artisan migrate --force

check: lint test migrate-check ## Everything CI should run

build: ## Production frontend build
	cd $(FRONTEND) && BACKEND_URL=http://127.0.0.1:$(BACKEND_PORT) npm run build

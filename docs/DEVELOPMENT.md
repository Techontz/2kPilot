# Development

```
frontend/        Next.js 16 + TypeScript + Tailwind v4 — src/app (routes), src/features (screens),
                 src/components (ui, layout, charts, providers), src/lib (api client, hooks, types)
backend/         Laravel 13 — app/Http/Controllers/Api, app/Services, app/Policies, app/Jobs,
                 app/Console/Commands, config/tradepilot.php, config/brokers.php, database/migrations, tests/
trading-engine/  Python package `fxrobot` — internal/ (API for Laravel), broker_engine, strategy_engine,
                 risk_engine, execution_engine, trading_engine, backtesting, market_data, services, tests/
```

## Commands

```bash
make dev            # everything (needs MySQL and Redis running)
make worker         # only the queue workers (php artisan horizon)
make test           # Laravel + engine + frontend unit tests
make lint           # Pint, ruff, mypy (strict), ESLint, TypeScript
make migrate-check  # migrations from scratch + rollback
make e2e            # browser tests: real Laravel + engine + MySQL + production build in Chrome
make check          # lint + test + migrate-check
```

Test databases (MySQL on `127.0.0.1:3308` by default — adjust `phpunit.xml`, `TEST_DATABASE_URL`, `E2E_DB_PORT`): `tradepilot_test` (Laravel), `tradepilot_engine_test` (engine), `tradepilot_e2e` (browser tests, recreated each run). Laravel tests use `QUEUE_CONNECTION=sync` and `CACHE_STORE=array`, so they don't need Redis.

## Rules of thumb

* Business rules live in Laravel (accounts, permissions, workflow) or the engine (trading math and broker I/O) — never in React.
* Strategies never import broker code. The risk engine is never skipped.
* Every record belongs to a user: scope indexes to the current user and authorise every bound record with its policy.
* Anything that changes money or settings is audited.
* Money/prices are decimal strings in the API; format only for display.
* Laravel ↔ engine calls go through `App\Services\Engine\EngineClient` (signed).

# Development

## Quality gates

```bash
make check        # ruff + ruff format + strict mypy + pytest (MySQL) + ESLint + tsc + Vitest + alembic check
make e2e          # Playwright against the real backend + production build (Google Chrome)
make bridge-test  # mt5_bridge: pytest + ruff + strict mypy
```

| Suite | Count | Where |
|---|---|---|
| Backend unit + integration (real MySQL 8) | 700+ | `backend/tests/` |
| MT5 bridge (fake MT5 module) | 108 | `mt5_bridge/tests/` |
| Frontend unit (Vitest) | 35 | `frontend/src/**/*.test.ts(x)` |
| Browser E2E (Playwright) | 11 | `frontend/e2e/` |

Notable backend suites: `test_risk_engine` (one test per rule and condition), `test_backtesting` (look-ahead and leakage), `test_execution` and `test_reliability` (lost responses, restarts, DB outages, duplicate signals, external positions, leadership lease), `test_mt5_bridge_contract` (backend client against the real bridge app), `test_engine_pipeline` (end-to-end paper trading), and `test_api_*` (security: secrets never returned, viewer and CSRF enforcement).

## Conventions

* **Routes are thin**: validate, call a service, serialize. Rules live in services and engines.
* **Money and prices are `Decimal`**; timestamps are aware UTC (stored through `UTCDateTime`).
* **Safety-relevant changes are audited** in the same transaction.
* **Anything uncertain fails closed**: a risk rule that can't be evaluated rejects the trade, and an uncertain order is reconciled, never resent.
* Strategies never import broker adapters. Adapters map every native error onto `broker_engine.errors`.
* No asserts for runtime safety checks (they vanish under `python -O`); raise explicit errors instead.
* Frontend: no trading logic in React; never display invented numbers (show `—` and say why); explain jargon with `<Term>`; colour is semantic (`live` is reserved for LIVE mode).

## Useful fixtures (`backend/tests/conftest.py`)

`client`, `app_factory(**settings)`, `db`, `owner`, `viewer`, `owner_client`, `login()`, `fresh_heartbeat(db)`. In `tests/paper_helpers.py`: `make_paper()` and `make_market()`. In `tests/test_engine_pipeline.py`: `setup_trading()` and `run_until()`.

## Adding an endpoint

1. Put the business logic in `services/…`, and audit if it changes state.
2. Add a thin route in `api/v1/<domain>.py` with `OwnerDep` for mutations, then include it in `api/v1/__init__.py`.
3. Add frontend types in `src/lib/types.ts`.
4. Add tests: 401, viewer 403, CSRF 403, validation 4xx, and the happy path.

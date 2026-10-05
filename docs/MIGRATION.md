# Migration: FastAPI monolith → Laravel + Next.js + isolated trading engine

Starting point: commit `48ec28c` (FastAPI backend with all engines, Next.js dashboard, MT5 bridge, 700+ tests).
Target: **Laravel** as the primary application/API, **Next.js** as the UI, **MySQL** as the database, and the Python engines kept as an isolated **trading-engine** service.

## Matrix

| Existing feature | Decision | New home | Reason |
|---|---|---|---|
| Strategy engine (contract, indicators, look-ahead-safe views, Trend Pullback V1) | **Keep** | `trading-engine/strategy_engine` | Pure, tested numeric code; no reason to rewrite |
| Risk engine (rules, sizing, limits) | **Keep + extend** | `trading-engine/risk_engine` | Added symbol exposure, trading-hours window, broker-reported market hours, manual-ticket volume check |
| Execution engine (intent saved before send, idempotency key, UNKNOWN → reconcile, never re-send) | **Keep** | `trading-engine/execution_engine` | Core safety guarantee, heavily tested |
| Reconciliation & restart recovery, external positions | **Keep** | `trading-engine/execution_engine/reconciliation.py` | Unchanged behaviour; Deriv supported via `OrderHint` |
| Trading engine supervisor (lease, heartbeat, worker threads) | **Keep** | `trading-engine/trading_engine` | Long-running loop belongs in the engine process |
| Paper broker + synthetic/replay market | **Keep** | `trading-engine/broker_engine/adapters/paper*.py` | Learning without money |
| MT5 bridge adapter + Windows bridge | **Keep** | `trading-engine/…/mt5_bridge.py`, `mt5_bridge/` | macOS can't run the MT5 library |
| Broker contract & manager | **Keep + extend** | `broker_engine/interface.py`, `manager.py` | Added `capabilities`, `OrderHint`, explicit disconnect |
| Deriv | **New** | `broker_engine/adapters/deriv*.py`, Laravel OAuth | Official 2026 Deriv API |
| Backtester + validation service | **Keep** | `trading-engine/backtesting` | Look-ahead protections preserved; now run by a Laravel queue job |
| Market data (sessions, conversion, resample, validation, CSV, synthetic) | **Keep** | `trading-engine/market_data` | |
| Metrics (`analytics/metrics.py`) | **Keep** for backtests, **reimplement** for live analytics | `backend/app/Services/Analytics/Metrics.php` | Laravel serves analytics; identical definitions, unit-tested |
| Users, Argon2 passwords, server-side sessions, CSRF | **Replace** | Laravel auth + Sanctum SPA sessions + CSRF (bcrypt) | Framework-native, plus **MFA (TOTP + recovery codes)** |
| Login rate limiting | **Reimplement** | Laravel `RateLimiter` (login, MFA, trading, broker) | |
| Audit log (append-only triggers, masking) | **Reimplement** | `audit_logs` (MySQL triggers) + `AuditLogger` + `Masker` | Refusals are audited outside transactions so they are never rolled back |
| Kill switch, operating mode, LIVE lock, emergency stop | **Reimplement** | `TradingControl` (Laravel) | Same rules; LIVE now also requires MFA. Engine still reads `system_state` every tick |
| Broker wizard backend (test, verify environment, save disabled, archive with history) | **Reimplement** | `BrokerService` (Laravel) + engine `/internal/connections/test` | Laravel owns UX and secrets; engine proves the connection |
| Credential encryption (Fernet) | **Replace** | AES-256-GCM, Laravel Encrypter format, `BROKER_CREDENTIALS_KEY` | Both PHP and Python read the same format (cross-language test) |
| Risk profiles CRUD | **Reimplement** | Laravel + `RiskProfileRequest` | Same validation rules as `RiskLimits.validate` |
| Strategy versions & assignments (immutable, paused by default) | **Reimplement** | `StrategyService` (Laravel); params validated by the engine | |
| Readiness checklist | **Removed (for now)** | — | Superseded by LIVE lock + MFA + password + phrase; documented in ROADMAP |
| Alembic migrations | **Replace** | Laravel migrations | Laravel owns the schema; engine tests build their schema with `php artisan migrate:fresh` |
| Public FastAPI API (`/api/v1`) & SSE stream | **Replace** | Laravel REST `/api/*`; dashboard polls | The engine API is internal (HMAC, loopback) |
| Notifications | **Keep** (engine) + Laravel notifier | | Watchdog, security and daily-summary notifications added |
| Next.js dashboard (14 pages) | **Rebuild** | `frontend/` (15 pages + wizard + instrument page + login/MFA) | New API, redesigned, Trade page added |
| CLI `fxrobot create-user` | **Replace** | `php artisan fx:user`; `fxrobot serve` remains for the engine | |

## Behavioural guarantees and where they are tested now

| Guarantee | Tests |
|---|---|
| Risk controls (every rule, sizing, exposure, new rules) | `trading-engine/tests/test_risk_engine.py`, `test_manual_orders.py` |
| Manual orders cannot bypass risk | `test_manual_orders.py`, Laravel `TradeTest`, E2E `02-paper-trading` |
| Backtesting accuracy / no look-ahead | `test_backtesting.py` |
| Execution idempotency & duplicate protection | `test_execution.py`, `test_reliability.py`, `test_manual_orders.py::…idempotency…`, `test_deriv_adapter.py::…never re-sent…` |
| Reconciliation & restart recovery | `test_reliability.py`, `test_deriv_engine.py` |
| Journaling | `test_engine_pipeline.py`, Laravel `MarketsAndRecordsTest` |
| Auditability (append-only, masking) | Laravel `AuditAndSecurityTest` |
| Paper trading | `test_paper_broker.py`, E2E |
| MT5 architecture | `test_mt5_bridge_contract.py`, `mt5_bridge/tests` |
| Strategy versioning | Laravel `StrategiesTest` |
| LIVE lock | Laravel `TradingControlTest`, `BrokersTest`, engine risk tests |
| Schema compatibility | every engine test runs on the Laravel-migrated schema |

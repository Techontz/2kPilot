# Database

PostgreSQL 16, SQLAlchemy 2 ORM, and Alembic migrations in `backend/src/fxrobot/db/migrations/`.

Principles:
* Relational models with foreign keys, constraints and indexes. JSON(B) is only for genuinely flexible data, such as strategy parameters or audit details.
* Deterministic constraint names (`db/base.py`) keep migrations reviewable.
* All timestamps are `timestamptz` in UTC. Money and prices will use `NUMERIC`.
* `alembic check` runs in CI, so models and migrations can't drift apart.

## Implemented (migration `0001`)

### `users`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| email | varchar(320) unique | CHECK `email = lower(email)` |
| display_name | varchar(120) | |
| password_hash | varchar(255) | Argon2id |
| role | enum `user_role` (`owner`, `viewer`) | |
| is_active | bool, default true | |
| last_login_at, created_at, updated_at | timestamptz | |

### `user_sessions`
Server-side sessions, which can be revoked instantly.
| Column | Notes |
|---|---|
| token_hash | SHA-256 of the session token, unique. The raw token is never stored |
| csrf_token_hash | SHA-256 of the per-session CSRF token |
| expires_at / last_seen_at / revoked_at | absolute expiry, idle timeout, logout |
| ip_address, user_agent | context |

FK `user_id → users` ON DELETE CASCADE. Index `(user_id, revoked_at)`.

### `audit_logs` (append-only)
| Column | Notes |
|---|---|
| id | bigserial |
| occurred_at | indexed |
| actor_user_id | FK → users ON DELETE SET NULL (history survives user deletion) |
| actor_label | email or `system`, kept even if the user is deleted |
| action | e.g. `trading.kill_switch.engaged`, indexed with `occurred_at` |
| outcome | enum `success` / `failure` / `denied` |
| target_type, target_id, ip_address, user_agent, correlation_id | context |
| details | JSONB, masked before insert |

A `BEFORE UPDATE OR DELETE` trigger (`audit_logs_append_only`) rejects any modification. The only exception is the FK's `SET NULL` of `actor_user_id`.

### `system_state` (singleton, `CHECK id = 1`)
| Column | Default | Notes |
|---|---|---|
| trading_mode | `DEMO` | enum `trading_mode`: BACKTEST, DEMO, LIVE |
| kill_switch_engaged | **true** | a fresh install cannot trade |
| kill_switch_reason / _changed_at / _changed_by | | |
| mode_changed_at / mode_changed_by | | |

The migration seeds the row. If it's ever missing, the service recreates it with the kill switch **engaged**.

## Planned schema (by phase)

| Phase | Tables |
|---|---|
| 2 Brokers | `broker_connections` (connector id, label, **encrypted** credentials, status), `trading_accounts` (broker account id, environment DEMO/LIVE/UNKNOWN, currency, trading_enabled) |
| 3 Market data | `symbols` (per connection: digits, point, contract size, volume limits), `candle_sets` (metadata: symbol, timeframe, range, source, checksum). Bulk candles in a partitioned `candles` table or Parquet files, decided in Phase 3 |
| 4 Strategies | `strategies`, `strategy_versions` (immutable params JSONB and a code version), `strategy_assignments` (strategy version × account × symbols, enabled flag) |
| 5 Risk | `risk_profiles` (typed limit columns, not JSON), `risk_events` (violations) |
| 5–7 Trading | `signals` (every intention, with risk decision and reason), `orders` (client_order_id **unique**, broker ids, status incl. UNKNOWN), `trades`, `positions` |
| 6 Backtesting | `backtests` (config, data range, cost assumptions, split periods), `backtest_trades`, `performance_snapshots` |
| 7 Notifications | `notifications` (type, severity, read_at), `notification_channels` |
| any | `system_settings` (typed key/value for operator-level settings) |

Idempotency and reconciliation rely on `orders.client_order_id` being unique and always sent to the broker. See [RISK_ENGINE.md](RISK_ENGINE.md).

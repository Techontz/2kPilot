# Database (MySQL 8)

SQLAlchemy 2 ORM, PyMySQL driver, and Alembic migrations in `backend/src/fxrobot/db/migrations/versions/`:

| Revision | Contents |
|---|---|
| `0001` | MySQL baseline: `users`, `user_sessions`, `audit_logs` (append-only triggers), `system_state` (seeded: DEMO, kill switch **engaged**) |
| `0002` | Trading schema: every other table below, plus the engine lease/heartbeat columns on `system_state` |

## MySQL-specific choices

| Topic | Choice |
|---|---|
| Time | `DATETIME(6)` storing **naive UTC** through the `UTCDateTime` type, which returns aware UTC datetimes. Each connection runs `SET time_zone='+00:00'` so `CURRENT_TIMESTAMP(6)` is UTC |
| Strictness | Each connection sets `STRICT_ALL_TABLES`, `NO_ZERO_DATE` and `ERROR_FOR_DIVISION_BY_ZERO` (no silent truncation of money) |
| Isolation | `READ COMMITTED`, so long-running engine loops always read fresh rows |
| Enums | `VARCHAR` + `CHECK` (not native `ENUM`): portable and easy to extend |
| JSON | MySQL `JSON` for genuinely flexible data only (strategy parameters, evaluation checks, reports, masked audit details) |
| Money / prices / lots | `DECIMAL(20,6)` / `DECIMAL(24,10)` / `DECIMAL(16,4)` |
| UUID keys | `CHAR(32)` |
| Charset | `utf8mb4` / `utf8mb4_0900_ai_ci`. Lower-case email is enforced with a binary CHECK |
| Audit log | `BEFORE UPDATE` / `BEFORE DELETE` triggers raise `SIGNAL 45000`. FK cascades don't fire triggers, so deleting a user still sets `actor_user_id` to NULL |
| DDL | MySQL DDL is **not transactional**. Back up before migrating production; a failed migration can leave partial tables |

## Tables

| Table | Purpose / key constraints |
|---|---|
| `users`, `user_sessions` | Accounts (Argon2id hashes). Sessions store only SHA-256 token hashes |
| `audit_logs` | Append-only record of security and trading actions |
| `system_state` | Singleton (`CHECK id = 1`): mode, kill switch, engine lease/heartbeat |
| `system_settings` | Typed key/value store for operator settings (reserved) |
| `broker_connections` | Connector type, non-secret settings, **Fernet-encrypted credentials**, status |
| `trading_accounts` | Broker-reported environment (PAPER/DEMO/LIVE/UNKNOWN), balances, `trading_enabled` (default off), risk profile. Unique `(connection, broker_account_id)` |
| `account_snapshots` | Balance/equity history → equity curves and drawdown |
| `broker_symbols` | Symbol specifications per connection |
| `paper_states` | Persisted paper-simulator state (restart recovery) |
| `datasets`, `candles` | Candle series metadata (source, range, gaps, checksum) + OHLCV, PK `(dataset_id, time)` |
| `strategies`, `strategy_versions` | Immutable parameter versions |
| `strategy_assignments` | Version × account × symbol, `PAUSED` by default. Unique `(account, strategy, symbol)` |
| `strategy_evaluations` | Why each closed bar did or didn't produce a signal |
| `risk_profiles` | Typed limit columns (not JSON) |
| `signals` | Intentions + every risk check + rejection reason. **Unique `(assignment, bar_time, side)`** = duplicate-signal protection |
| `orders` | Every broker instruction. **Unique `client_order_id`** = idempotency key. Status includes `UNKNOWN` |
| `trades` | Position lifecycle from open to close (the unit for journal and analytics) |
| `trade_events` | The journal timeline |
| `backtests`, `backtest_trades` | Reproducible runs (config, data checksum, results), with parent/child runs for validation |
| `notifications` | In-app alerts |

## Adding a migration

```bash
cd backend
.venv/bin/alembic revision --autogenerate -m "describe change" --rev-id 0003
# REVIEW the file: server defaults, enum CHECKs (the Enum's own CHECK is enough), data migrations, downgrade
.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
.venv/bin/alembic check
```

Autogenerate renders timestamp columns as `DT` (`DATETIME(6)` on MySQL), so migrations don't import application code.

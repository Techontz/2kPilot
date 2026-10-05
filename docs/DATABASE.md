# Database (MySQL 8)

**Laravel owns the schema**: `backend/database/migrations`. The trading engine maps the same tables with SQLAlchemy (`trading-engine/src/fxrobot/models`) and never creates or alters them. Every engine test run builds its database with `php artisan migrate:fresh`, so the two can't drift apart.

```bash
cd backend
php artisan migrate                 # apply
php artisan migrate:fresh           # rebuild from scratch (deletes data!)
php artisan migrate:rollback        # undo the last batch
make migrate-check                  # fresh → full rollback → migrate again (on twokfx_test)
```

Conventions: UTC everywhere (`DATETIME(6)`, connection time zone `+00:00`), UUID keys as `CHAR(36)`, money `DECIMAL(20,6)`, prices `DECIMAL(24,10)`, volumes `DECIMAL(16,4)`, enumerations as `VARCHAR` + `CHECK` constraints, READ COMMITTED isolation.

| Table | What |
|---|---|
| `users`, `sessions`, `personal_access_tokens` | Logins, MFA (encrypted), sessions |
| `audit_logs` | Append-only audit trail (triggers) |
| `system_state` | Single row: kill switch (starts ENGAGED), operating mode, engine lease + heartbeat |
| `risk_profiles` | Typed limits; default *Conservative (default)* seeded |
| `broker_connections` | Connector, expected environment, settings, **encrypted credentials**, status |
| `trading_accounts` | Broker-reported environment, currency, balances, capabilities, trading switch, risk profile |
| `account_snapshots` | Balance/equity history (equity curve, drawdown) |
| `broker_symbols` | Instruments per connection (category, market open) |
| `paper_states` | Persisted paper simulator state |
| `strategies`, `strategy_versions` | Catalogue and immutable parameter sets |
| `strategy_assignments`, `strategy_evaluations` | Version × account × symbol; why each bar did/didn't signal |
| `signals` | Strategy or MANUAL intentions + every risk check; unique per assignment/bar/side; manual idempotency key |
| `orders` | Every broker instruction; `client_order_id` unique |
| `trades` | Positions open → closed |
| `trade_events` | The journal |
| `datasets`, `candles` | Historical data |
| `backtests`, `backtest_trades` | Runs, metrics, reports, trades |
| `notifications` | In-app notifications |
| `jobs`, `failed_jobs`, `cache*` | Laravel queue and cache |

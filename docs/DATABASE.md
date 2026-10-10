# Database (MySQL 8)

**Laravel owns the schema**: `backend/database/migrations`. The trading engine maps the same tables with SQLAlchemy (`trading-engine/src/fxrobot/models`) and never creates or alters them. Every engine test run builds its database with `php artisan migrate:fresh`, so the two can't drift apart.

```bash
cd backend
php artisan migrate                 # apply
php artisan migrate:fresh           # rebuild from scratch (deletes data!)
php artisan migrate:rollback        # undo the last batch
make migrate-check                  # fresh → full rollback → migrate again (on tradepilot_test)
                                    # (uses DB_PORT from backend/.env; e.g. DB_PORT=3308 make migrate-check)
```

Conventions: UTC everywhere (`DATETIME(6)`, connection time zone `+00:00`), UUID keys as `CHAR(36)`, money `DECIMAL(20,6)`, prices `DECIMAL(24,10)`, volumes `DECIMAL(16,4)`, enumerations as `VARCHAR` + `CHECK` constraints, READ COMMITTED isolation.

Orders, trades, signals, assignments, snapshots, evaluations and the journal belong to the owner of their trading account.

| Table | What |
|---|---|
| `users`, `sessions`, `personal_access_tokens` | Logins, MFA (encrypted), sessions |
| `audit_logs` | Append-only audit trail (triggers) |
| `user_trading_states` | One row per user: mode (DEMO/LIVE, default DEMO), STOP switch (starts ENGAGED) + reason, LIVE authorisation time and limits snapshot |
| `system_state` | Single row: platform-wide admin halt (default not halted), engine lease + heartbeat |
| `risk_profiles` | Typed limits, owned by a user (name unique per user); every new user gets *Beginner*. Pip/lot limits apply to SPOT; `stake_amount` (NOT NULL, default 1.00), `max_stake_amount`, `max_daily_loss_amount`, `max_consecutive_losses`, `daily_profit_target_amount` size and bound contracts (CHECK: stake > 0 and ≤ max stake) |
| `broker_connections` | Owner, connector (`paper` / `deriv`), expected environment, settings, **encrypted credentials**, status |
| `trading_accounts` | Owner (denormalised from the connection), broker-reported environment, currency, balances, capabilities, trading switch, risk profile |
| `account_snapshots` | Balance/equity history (equity curve, drawdown) |
| `broker_symbols` | Instruments per connection (category, market open) |
| `paper_states` | Persisted paper simulator state |
| `strategies`, `strategy_versions` | Catalogue (`user_id` NULL = built-in template with a unique `slug`; users' strategies are theirs). `key` = implementation (`rules` for builder/template/AI/import strategies), `source` (template/builder/ai/import/copy, CHECK), `summary`, `details` (JSON: how it works, struggles, suggestions, difficulty, disclaimer), `copied_from_id`, `archived_at`. Versions are immutable parameter sets (the rule set for `rules`) with a plain-English `rules_text`. Rule templates are seeded by migration `…000510_seed_strategy_templates` from `database/data/strategy_templates.json` |
| `strategy_assignments`, `strategy_evaluations` | Version × account × symbol + the **contract spec** (`contract_family` SPOT/RISE_FALL/MULTIPLIER, `duration`, `duration_unit` t/s/m/h/d, `allow_equals`, `stake` (NULL = profile stake), `multiplier`, `take_profit_amount`, `stop_loss_amount`; CHECKs per family); why each bar did/didn't signal |
| `signals` | Strategy or MANUAL intentions + every risk check; unique per assignment/bar/side; manual idempotency key; `contract_family`, `contract_type`, `stake`; `stop_loss` NULL only for contracts |
| `orders` | Every broker instruction; `client_order_id` unique; contract columns as on `trades` |
| `trades` | Positions open → closed. Contract columns (NULL / `SPOT` for lot trades): `contract_family`, `contract_type` (CALL/PUT/CALLE/PUTE/MULTUP/MULTDOWN), `broker_contract_id`, `stake`, `payout`, `multiplier`, `duration`, `duration_unit`, `expires_at`, `entry_spot`, `exit_spot`, `fees` (commission, positive), `outcome` (OPEN/WON/LOST/SOLD/CANCELLED), `longcode`. Contract trades have `volume` = 1 (one contract) and `risk_amount` = stake |
| `trade_events` | The journal |
| `datasets`, `candles` | Historical data (`user_id` NULL = shared) |
| `backtests`, `backtest_trades` | Runs (owned by a user), metrics, reports, trades. `backtests.config` holds `contract`, `payout_ratio`, `payout_ratio_is_estimate`, `commission_pct`; `backtest_trades` adds `contract_type`, `stake`, `payout`, `outcome` (`stop_loss` NULL for Rise/Fall) |
| `notifications` | In-app notifications per recipient (`user_id` NULL = platform notification for admins) |
| `jobs`, `failed_jobs`, `cache*` | Laravel database queue/cache tables (Redis is used by default) |

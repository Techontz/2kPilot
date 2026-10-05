# Architecture

## The big picture

```
                    ┌──────────────────────────── your computer ────────────────────────────┐
Browser ──────────► │ Next.js dashboard (frontend/)                                          │
 (only talks to     │   /api/*, /sanctum/*  ──proxy──►  Laravel (backend/)                   │
  this origin)      │                                     • login, MFA, sessions, policies   │
                    │                                     • REST API, validation, audit log  │
                    │                                     • Broker Center, risk profiles,    │
                    │                                       strategies, analytics, journal   │
                    │                                     • queue jobs (backtests)           │
                    │                                     • scheduler (engine watchdog …)    │
                    │                                            │ HMAC-signed, 127.0.0.1     │
                    │                                            ▼                            │
                    │                                   Trading engine (trading-engine/)     │
                    │                                     • Broker Manager + adapters        │
                    │                                     • strategies → risk → execution     │
                    │                                     • reconciliation, backtester       │
                    │                                            │                            │
                    │                    MySQL 8  ◄──────────────┴──── both read/write ──────│
                    └──────────────────────────────────────┬─────────────────────────────────┘
                                                           │
                       ┌───────────────────────────────────┼─────────────────────────────┐
                       ▼                                   ▼                             ▼
                 Paper simulator                 Deriv API (api.derivws.com)    mt5_bridge (Windows) → MT5 → broker
                 (inside the engine)             REST + OTP WebSocket            HTTPS + HMAC
```

| Part | Technology | Responsibility |
|---|---|---|
| `frontend/` | Next.js 16, TypeScript, Tailwind v4 | The user interface only. No business rules. Polls the API for live data. |
| `backend/` | Laravel 13, PHP 8.4, Sanctum | The primary application: authentication + MFA, authorization (policies), validation, REST API, audit log, Broker Center, encrypted credentials, risk profiles, strategy versions/assignments, analytics, journal, notifications, queue jobs, scheduler. **Owns the MySQL schema** (migrations). |
| `trading-engine/` | Python 3.11, FastAPI (internal), SQLAlchemy | Everything quantitative and broker-facing: broker adapters, Broker Manager, market data, strategies, risk engine, execution engine, reconciliation, paper simulator, backtester. |
| `mt5_bridge/` | Python on Windows | Runs beside the MetaTrader 5 terminal (the MT5 library only works on Windows). |
| MySQL 8 | | The single database. |

### Why the trading engine stays in Python

The engines (risk rules, idempotent execution, reconciliation, paper simulator, look-ahead-safe backtester) were already implemented and covered by 500+ tests. Rewriting them in PHP would add risk without benefit: numeric work (numpy, Decimal), long-running broker connections (Deriv WebSocket with a reader thread) and the MT5 bridge client fit a long-running Python process, whereas PHP requests are short-lived. So Laravel is the primary backend and orchestrator, and the engine is an isolated internal service that **only Laravel can call** (127.0.0.1 + HMAC signature + timestamp + nonce).

## The trading pipeline (identical for paper, demo and live)

```
market data → strategy → signal → risk engine → execution engine → broker adapter → broker
                                     ▲
                manual ticket ───────┘   (Trade page: same risk engine, same execution engine)
```

Every engine tick (2 s): `advance → reconcile orders & positions → sync account & snapshots →
[STOP TRADING engaged? stop here] → [unresolved order? no new entries] → evaluate enabled strategies on newly closed bars`.

* **Strategies never call a broker.** They return a `SignalIntent` (side, entry, mandatory stop loss, take profit, reasons).
* **The risk engine decides** (19 rules + sizing + exposure + margin). Every rule's result is stored on the signal.
* **The execution engine** writes the order (with a unique `client_order_id`) **before** sending it. An uncertain outcome becomes `UNKNOWN` and is reconciled with the broker — it is never re-sent.
* Everything is journaled (`trade_events`) under one correlation id: *market condition → signal → risk decision → order → broker response → position → exit → P/L*.

## Broker architecture

```
2kFX → Broker Manager → Broker Adapter → Broker API / Bridge → Trading Account
```

`BrokerAdapter` (`trading-engine/src/fxrobot/broker_engine/interface.py`) is the one contract. Every adapter normalises: authentication/connect, account (id, environment, currency, balance, equity, margin), symbols, quotes, candles, positions, pending orders, place/modify/close/cancel, trade history (deals), health, a reconciliation lookup, and **capabilities** (pending orders? partial close? volume unit?). Errors map onto one taxonomy where *rejected* (nothing happened) is distinct from *outcome unknown* (may have happened).

| Adapter | How | Notes |
|---|---|---|
| `PaperBroker` | In-process simulator | SYNTHETIC or replayed prices, margin, SL/TP, gaps, stop-out, fault injection |
| `DerivAdapter` | Deriv REST (accounts, one-time passwords) + trading WebSocket | Multiplier contracts; SL/TP prices ↔ money amounts; market orders only |
| `MT5BridgeAdapter` | HTTPS + HMAC to `mt5_bridge` | Contract-tested against the bridge app |

The `BrokerManager` holds one adapter per connection, connects lazily, reconnects with exponential back-off, writes CONNECTED / RECONNECTING / ERROR / DISCONNECTED to the database, and raises notifications. Adding a broker = one adapter class + one catalogue entry (`backend/config/brokers.php`); strategies never change.

## Data ownership

| Written by Laravel | Written by the engine |
|---|---|
| users, sessions, audit_logs, broker_connections (+ encrypted credentials), trading_accounts (settings), risk_profiles, strategy_versions, strategy_assignments, system_state (kill switch, mode), notifications (Laravel events) | connection status, account balances, account_snapshots, broker_symbols, paper_states, strategies (catalogue), strategy_evaluations, signals, orders, trades, trade_events, backtests results, datasets/candles, notifications, engine heartbeat & lease |

The engine reads the kill switch and the operating mode from `system_state` on every tick, so STOP TRADING takes effect within one tick even if Laravel is down.

## Secrets

Broker credentials are encrypted by Laravel with AES-256-GCM using `BROKER_CREDENTIALS_KEY` (separate from `APP_KEY`), stored in `broker_connections.credentials_encrypted`, decrypted only inside the engine when it connects, and never returned to the browser. See [SECURITY.md](SECURITY.md).

## Real-time updates

The dashboard polls: trading status every 5 s, positions every 3 s, quotes every 2–3 s, overview every 5 s (only while the tab is visible). REST is the single source of truth.

## Laravel jobs and scheduler

| What | Where | Why |
|---|---|---|
| `RunBacktest` (queue) | `app/Jobs/RunBacktest.php` | Backtests take minutes; the request returns immediately |
| `fx:engine-watchdog` (every minute) | scheduler | If the engine dies it cannot warn anyone — Laravel notifies once per outage |
| `fx:daily-summary` (21:05 UTC) | scheduler | One P/L summary per account that traded |
| `fx:prune` (daily) | scheduler | Old "no setup" evaluations and read notifications only — trades, orders, journal and audit are never pruned |

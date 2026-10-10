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
                    │                                     • Horizon queues on Redis          │
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
                       ┌───────────────────────────────────┴─────────────┐
                       ▼                                                 ▼
                 Paper simulator                               Deriv API (api.derivws.com)
                 (inside the engine)                           REST + OTP WebSocket
```

| Part | Technology | Responsibility |
|---|---|---|
| `frontend/` | Next.js 16, TypeScript, Tailwind v4 | The user interface only. No business rules. Polls the API for live data. |
| `backend/` | Laravel 13, PHP 8.4, Sanctum | The primary application: sign-up, authentication + MFA, authorization (per-user ownership policies, admin gates), validation, REST API, audit log, Broker Center, encrypted credentials, risk profiles, strategy versions/assignments, analytics, journal, notifications, queue jobs (Redis + Horizon), scheduler. **Owns the MySQL schema** (migrations). |
| `trading-engine/` | Python 3.11, FastAPI (internal), SQLAlchemy | Everything quantitative and broker-facing: broker adapters, Broker Manager, market data, strategies, risk engine, execution engine, reconciliation, paper simulator, backtester. |
| MySQL 8 | | The single database. |
| Redis | | Laravel queues (`default`, `notifications`, `backtests`) and cache. |

### Why the trading engine stays in Python

The engines (risk rules, idempotent execution, reconciliation, paper simulator, look-ahead-safe backtester) were already implemented and covered by 500+ tests. Rewriting them in PHP would add risk without benefit: numeric work (numpy, Decimal), long-running broker connections (Deriv WebSocket with a reader thread) fit a long-running Python process, whereas PHP requests are short-lived. So Laravel is the primary backend and orchestrator, and the engine is an isolated internal service that **only Laravel can call** (127.0.0.1 + HMAC signature + timestamp + nonce).

## The trading pipeline (identical for paper, demo and live)

```
market data → strategy → signal → risk engine → execution engine → broker adapter → broker
                                     ▲
                manual ticket ───────┘   (Trade page: same risk engine, same execution engine)
```

Every engine tick (2 s), per account: `advance → reconcile orders & positions → sync account & snapshots →
[not tradeable? stop here] → [unresolved order? no new entries] → evaluate enabled strategies on newly closed bars`.

An account is **tradeable** only if the platform is not halted, **its owner's** STOP switch is released, its environment fits the owner's mode (LIVE also needs the server lock off and the owner's LIVE authorisation), trading is enabled on it, and it has a risk profile. Otherwise the engine only monitors it (sync/reconcile). Account ticks never overlap: a tick that exceeds 45 s keeps running in the background, and later cycles skip that account ("previous tick still running") until it finishes. Across processes, the leadership lease (90 s) outlives a cycle and is renewed while ticks run, and every tick also holds a per-account MySQL lock (`GET_LOCK('tp:acct:<id>', 0)` on its own connection), so a second engine can never tick the same account concurrently.

* **Strategies never call a broker.** They return a `SignalIntent` (side, entry, mandatory stop loss, take profit, reasons).
* **The assignment's contract spec** decides what a BUY/SELL becomes: SPOT lots (Paper), or a Rise/Fall / Multiplier contract sized by a stake (see [BROKERS.md](BROKERS.md)).
* **The risk engine decides** (rules + sizing — lots for SPOT, a stake for contracts). Every rule's result is stored on the signal.
* **The execution engine** writes the order (with a unique `client_order_id`) **before** sending it. An uncertain outcome becomes `UNKNOWN` and is reconciled with the broker — it is never re-sent.
* Everything is journaled (`trade_events`) under one correlation id: *market condition → signal → risk decision → order → broker response → position → exit → P/L*.

## Broker architecture

```
2kPilot → Broker Manager → Broker Adapter → Broker API → Trading Account
```

`BrokerAdapter` (`trading-engine/src/fxrobot/broker_engine/interface.py`) is the one contract. Every adapter normalises: authentication/connect, account (id, environment, currency, balance, equity, margin), symbols, quotes, candles, positions, pending orders, place/modify/close/cancel, trade history (deals), health, a reconciliation lookup, and **capabilities** (pending orders? partial close? volume unit?). Errors map onto one taxonomy where *rejected* (nothing happened) is distinct from *outcome unknown* (may have happened).

| Adapter | How | Notes |
|---|---|---|
| `PaperBroker` | In-process simulator | SYNTHETIC (deterministic 1-minute feed, every timeframe M1…D1) or replayed prices, margin, SL/TP, gaps, stop-out, fault injection |
| `DerivAdapter` | Deriv REST (accounts, one-time passwords) + trading WebSocket | Rise/Fall and Multiplier contracts sized by a stake; market orders only |

The `BrokerManager` holds one adapter per connection, connects lazily, reconnects with exponential back-off, writes CONNECTED / RECONNECTING / ERROR / DISCONNECTED to the database, and raises notifications. Adding a broker = one adapter class + one catalogue entry (`backend/config/brokers.php`); strategies never change.

## Data ownership

| Written by Laravel | Written by the engine |
|---|---|
| users, sessions, audit_logs, broker_connections (+ encrypted credentials), trading_accounts (settings), risk_profiles, strategies (user copies), strategy_versions, strategy_assignments, user_trading_states (each user's STOP switch, mode, LIVE authorisation), system_state (platform halt), notifications (Laravel events) | connection status, account balances, account_snapshots, broker_symbols, paper_states, strategies (built-in catalogue), strategy_evaluations, signals, orders, trades, trade_events, backtests results, datasets/candles, notifications, engine heartbeat & lease |

Every record belongs to a user: `user_id` on broker connections, trading accounts, risk profiles, strategies and datasets (`NULL` = built-in/shared), backtests and notifications (`NULL` = platform notification for admins); orders, trades, signals and the journal inherit it through their account. API indexes show only the current user's records; admins can read any record but can't trade or change other users' accounts.

The engine reads the platform halt (`system_state`) and each owner's switch and mode (`user_trading_states`) on every tick, so STOP TRADING takes effect within one tick even if Laravel is down.

## Secrets

Broker credentials are encrypted by Laravel with AES-256-GCM using `BROKER_CREDENTIALS_KEY` (separate from `APP_KEY`), stored in `broker_connections.credentials_encrypted`, decrypted only inside the engine when it connects, and never returned to the browser. See [SECURITY.md](SECURITY.md).

## Real-time updates

The dashboard keeps one Server-Sent Events connection open to `GET /api/stream` (`app/Services/Live/LiveStream.php`). Every 2 s Laravel takes cheap fingerprints of the user's own records (trading switch/mode + platform halt + engine state, account balances, open and closed trades, unread notifications) and sends a named event when one changed (`trading.status`, `account.balance`, `trade.opened`, `trade.closed`, `notification`); the dashboard then refetches the affected REST endpoints. A connection lasts at most 55 s, then the browser reconnects. If the stream is unavailable the dashboard falls back to polling (trading status, positions, overview every few seconds while the tab is visible; quotes are always polled). REST stays the single source of truth — events carry only small hints. Sizing and proxy settings: [DEPLOYMENT.md](DEPLOYMENT.md#live-updates-sse).

## Laravel jobs and scheduler

| What | Where | Why |
|---|---|---|
| `RunBacktest` (`backtests` queue) | `app/Jobs/RunBacktest.php` | Backtests take minutes; the request returns immediately. Runs on its own Horizon supervisor (timeout 30 min, one try) |
| `tp:engine-watchdog` (every minute) | scheduler | If the engine dies it cannot warn anyone — Laravel notifies once per outage |
| `tp:daily-summary` (21:05 UTC) | scheduler | One P/L summary per account that traded |
| `tp:prune` (daily) | scheduler | Old "no setup" evaluations and read notifications only — trades, orders, journal and audit are never pruned |

Queues run under **Horizon** (`php artisan horizon`; `make dev` and `make worker` start it): `default` and `notifications` on one supervisor, `backtests` on another (connection `redis-long`). The dashboard at `/horizon` is for admins only.

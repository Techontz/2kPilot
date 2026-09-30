# 2kFX ROBOT

A Forex **trading research and automation platform**, built to show whether a strategy has a real edge *before* any real money is exposed.

The platform works end to end on paper today:

```
market data → strategy → signal → risk engine → execution engine → broker → reconciliation → journal → analytics
```

It runs on the built-in **PAPER / SIMULATION** broker on any computer, and it is ready for **MetaTrader 5 demo** accounts through a small Windows bridge service. **LIVE (real-money) trading is hard-locked** and stays that way until a deliberate live-readiness review.

> **Nothing in this repository claims a strategy is profitable.** Backtests on synthetic data say nothing about real markets, and past results never guarantee future results. The goal is to *measure*, honestly.

---

## What you get

| Area | What's there |
|---|---|
| **Brokers** | 7-step *Add Broker* wizard. The broker must confirm the account type (a "DEMO" that is really LIVE is refused). Credentials are encrypted at rest and never shown again. Connection status is shown as CONNECTED, DISCONNECTED, RECONNECTING or ERROR, with automatic reconnect and backoff. Environments are PAPER, DEMO and LIVE. |
| **MetaTrader 5** | `mt5_bridge/` is a Windows service beside the MT5 terminal. It uses HMAC-signed requests and responses, keeps an idempotency journal and converts server time to UTC. The backend talks to it through `MT5BridgeAdapter`. |
| **Paper broker** | A full simulator: margin, stop loss and take profit (stop first when a bar is ambiguous), gap fills, pending orders, stop-out, and simulated faults. It uses SYNTHETIC prices or replays stored history, and never runs ahead of real time. |
| **Market data** | Sessions, currency conversion, pip values, resampling with no look-ahead, and validation (gaps, spikes, bad bars). CSV import (MT5 exports and generic files), MT5 download, and a clearly labelled synthetic generator. |
| **Strategies** | Strategies are pure, explainable functions. Every closed bar records *why* it did or did not signal. **Trend Pullback V1** is fully configurable. Versions are immutable, and assignments start **paused**. |
| **Risk engine** | 20 centralized rules plus position sizing. No path bypasses it. Every rejection stores its reason. A rule that can't be evaluated fails closed. |
| **Execution** | The order intent is saved *before* sending, with an idempotency key. An uncertain outcome goes to reconciliation and the order is **never blindly re-sent**. Also covers restart recovery and detection of positions opened outside 2kFX. |
| **Backtesting** | The same strategy and risk code as live trading. Fills happen at the next bar's open, with spread, commission, slippage and swap. Modes: in-sample vs out-of-sample, walk-forward, and parameter sensitivity, with overfitting warnings. |
| **Journal & analytics** | The full lifecycle of every trade: signal → risk → order → fill → modifications → exit. Analytics come only from stored records. |
| **Dashboard** | 14 pages with a dark, premium, responsive design, live updates (SSE), a beginner glossary on hover, and a persistent LIVE banner. |
| **Safety** | The kill switch is engaged on a fresh install. Emergency stop is separate from closing positions. There's a LIVE hard lock and a live-readiness checklist, an append-only audit log, CSRF protection, Argon2 passwords and rate limiting. |

## Quick start (macOS/Linux, MySQL 8)

```bash
make setup                 # venv + npm + backend/.env with a new encryption key
# edit DATABASE_URL in backend/.env if your MySQL is not on 127.0.0.1:3306
make db                    # create the database + run migrations
make user EMAIL=you@example.com NAME=Conrad    # prompts for a password
make dev                   # API + trading engine + dashboard
```

Open **http://localhost:3000** and sign in. If ports 3000/8000 are taken: `make dev BACKEND_PORT=8421 FRONTEND_PORT=3421`.

Full instructions: [docs/SETUP.md](docs/SETUP.md). Day-to-day use: [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## Try paper trading in 5 minutes

1. **Brokers → Add broker → Paper / Simulation**, keep the defaults, then *Test connection → Verify → Save*.
2. On the account card, switch **Trading enabled** on (the default risk profile is already assigned).
3. **Strategies → Assign** → pick the paper account and `EURUSD` → **Enable**.
4. In the top bar, **Resume trading** → confirm.
5. Watch **Journal**, **Positions** and **Analytics**. Everything is marked PAPER.

## Repository layout

```
backend/        FastAPI app + all engines (Python package `fxrobot`), MySQL migrations, 700+ tests
  src/fxrobot/
    api/            HTTP routes (thin), SSE stream, serializers
    broker_engine/  BrokerAdapter contract, errors, registry, manager, adapters/ (paper, mt5_bridge)
    market_data/    sessions, conversion, resample, validation, store, CSV import, synthetic
    strategy_engine/ Strategy contract, indicators, views, Trend Pullback V1
    risk_engine/    rules, sizing, limits
    execution_engine/ submission, reconciliation, journal
    trading_engine/ per-account runner, supervisor (lease + heartbeat), risk context
    backtesting/    event-driven backtester + validation service
    analytics/      shared performance metrics
    notifications/  in-app notifications + channel interface
    services/       business rules used by the API
frontend/       Next.js 16 dashboard (TypeScript, Tailwind v4), Vitest + Playwright E2E
mt5_bridge/     Windows service for MetaTrader 5 (runs beside the terminal)
docs/           architecture, setup, operations and safety documentation
```

## Commands

```bash
make check        # lint + types + backend & frontend tests + migration drift check
make e2e          # browser end-to-end tests (real backend + production build)
make bridge-test  # MT5 bridge tests (fake MT5 module)
make help         # everything else
```

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Setup](docs/SETUP.md) · [User guide](docs/USER_GUIDE.md) · [Development](docs/DEVELOPMENT.md) · [Database](docs/DATABASE.md) · [Brokers](docs/BROKERS.md) · [MT5 bridge setup](docs/MT5_BRIDGE_SETUP.md) · [MT5 bridge protocol](docs/MT5_BRIDGE_PROTOCOL.md) · [Strategies](docs/STRATEGIES.md) · [Risk engine](docs/RISK_ENGINE.md) · [Backtesting](docs/BACKTESTING.md) · [Security](docs/SECURITY.md) · [Deployment](docs/DEPLOYMENT.md) · [Roadmap & live readiness](docs/ROADMAP.md)

## Safety principles

1. Strategies propose. The **risk engine decides**. No code path bypasses it.
2. The kill switch starts **engaged**. Stopping takes one click; resuming is deliberate. Stopping never closes positions; closing everything is a separate emergency action.
3. **LIVE is hard-locked** by server config (`LIVE_TRADING_ENABLED=false`). Enabling it also needs your password and a typed confirmation. The system never silently switches from demo to live.
4. When state is uncertain, the **safest outcome wins**. An account with unresolved orders takes no new entries, and an order is never resent until the broker confirms it didn't execute.
5. Nothing fake: no invented balances, trades or broker connections. PAPER and SYNTHETIC are labelled everywhere.

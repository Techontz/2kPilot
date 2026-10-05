# 2kFX ROBOT

A Forex **trading research and automation platform**: learn on paper, prove an edge on demo, and only then — deliberately — consider real money.

```
market data → strategy → signal → risk engine → execution engine → broker adapter → broker → reconciliation → journal → analytics
```

| | |
|---|---|
| **Frontend** | `frontend/` — Next.js 16, TypeScript, Tailwind CSS. Dark, responsive dashboard. |
| **Backend** | `backend/` — Laravel 13 (PHP 8.4): REST API, sign-in + MFA, policies, audit log, Broker Center, queue jobs, scheduler. Owns the MySQL schema. |
| **Trading engine** | `trading-engine/` — isolated Python service: broker adapters, strategies, risk engine, execution, reconciliation, paper simulator, backtester. Only Laravel can call it. |
| **Database** | MySQL 8 |
| **MT5 bridge** | `mt5_bridge/` — runs on Windows next to MetaTrader 5 |

> **Nothing here claims a strategy is profitable.** Backtests on synthetic data say nothing about real markets, and past results never guarantee future results.

## Brokers

| Broker | Status |
|---|---|
| **Paper Trading** | Available — simulated, no money, labelled PAPER everywhere |
| **Deriv** | Real integration with Deriv's current official API (OAuth 2.0 + PKCE or personal access token). Needs your Deriv App ID. |
| **MetaTrader 5** | Via the Windows bridge (HMAC-signed HTTPS) |

## Quick start (macOS / Linux)

```bash
make setup                                  # composer, venv, npm, env files, shared secrets
# set DB_* in backend/.env and DATABASE_URL in trading-engine/.env (same MySQL database)
make db                                     # Laravel migrations
make user EMAIL=you@example.com NAME=Conrad # asks for a password
make dev                                    # engine + API + queue + scheduler + dashboard
```

Open **http://localhost:3421**. Then: Settings → Security (turn on MFA) → Brokers → Add broker → Paper Trading.

## Safety principles

1. Strategies propose; the **risk engine decides**. Manual tickets pass the same checks. Nothing bypasses it.
2. **STOP TRADING** is always one click away and starts engaged on a fresh install. It never closes positions — **Close positions** is a separate, deliberate action.
3. **LIVE is locked** (`LIVE_TRADING_ENABLED=false`). Enabling LIVE mode also needs MFA, your password and a typed phrase. An account the broker won't confirm as demo/live never trades.
4. When state is uncertain, the safe outcome wins: an order whose outcome is unknown is reconciled with the broker, never re-sent; an account with an unresolved order takes no new trades.
5. Nothing fake: no invented balances, trades or connections. A broker shows CONNECTED only after a real connection.

## Commands

```bash
make check     # lint + all tests + migration rollback check
make e2e       # browser tests: real Laravel + engine + MySQL + production build in Chrome
make help      # everything else
```

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Setup](docs/SETUP.md) · [User guide](docs/USER_GUIDE.md) · [Brokers & Deriv](docs/BROKERS.md) · [MT5 bridge setup](docs/MT5_BRIDGE_SETUP.md) · [MT5 bridge protocol](docs/MT5_BRIDGE_PROTOCOL.md) · [Strategies](docs/STRATEGIES.md) · [Risk engine](docs/RISK_ENGINE.md) · [Backtesting](docs/BACKTESTING.md) · [Database](docs/DATABASE.md) · [Security](docs/SECURITY.md) · [Development](docs/DEVELOPMENT.md) · [Deployment](docs/DEPLOYMENT.md) · [Migration matrix](docs/MIGRATION.md) · [Roadmap](docs/ROADMAP.md)

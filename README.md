# 2kFX ROBOT

A Forex trading **research and automation platform**, built so you can find out whether a strategy has a real edge *before* any real money is exposed.

> **Status: Phase 1 — Foundation (complete).** The platform has authentication, a safety-first trading control layer (kill switch, operating modes, a LIVE hard lock), an audit trail, the broker abstraction that MetaTrader 5 will plug into, and the dashboard shell. **It cannot place trades yet.** No broker adapter, strategy or trading engine exists yet, and the UI says so plainly instead of showing sample numbers.

The first milestone is not "make money". It is:
**a trustworthy platform that can prove whether a strategy has an edge.** Correctness, safety, testability and observability come first. Strategy performance comes after that.

---

## What's in the box

| Area | State |
|---|---|
| FastAPI backend (`/api/v1`), typed config, JSON structured logs with correlation IDs and secret masking | ✅ |
| PostgreSQL + Alembic migrations (checked for drift in CI via `alembic check`) | ✅ |
| Auth: Argon2id passwords, revocable server-side sessions, httpOnly cookies, CSRF protection, login rate limiting | ✅ |
| Global **kill switch** (engaged by default), BACKTEST / DEMO / LIVE modes, **LIVE hard lock** | ✅ |
| Append-only audit log (enforced by a database trigger) | ✅ |
| Encryption for broker credentials at rest (Fernet, supports key rotation) | ✅ ready for Phase 2 |
| Broker-neutral adapter interface and DTOs (MT5-ready) | ✅ interface only |
| Dashboard: Overview, Risk Management, Trading, Brokers, Settings/Audit, plus honest "arrives in Phase N" screens | ✅ |
| MT5 adapter, market data, strategies, risk engine, backtesting, execution | ⏳ Phases 2–7 |

## Quick start (local, macOS/Linux)

Prerequisites: Python 3.11+, Node 20+ (24 recommended), and PostgreSQL 16 running locally.

```bash
make setup                                   # venv + pip + npm
createdb fxrobot
cp .env.example backend/.env
backend/.venv/bin/fxrobot generate-key       # paste into SECRET_ENCRYPTION_KEY in backend/.env
make migrate
backend/.venv/bin/fxrobot create-user --email you@example.com --name "Your Name"
make backend      # terminal 1 → http://127.0.0.1:8000/api/docs
make frontend     # terminal 2 → http://localhost:3000
```

Full instructions are in [docs/SETUP.md](docs/SETUP.md).

## Repository layout

```
backend/                 Python package `fxrobot` (FastAPI + engines)
  src/fxrobot/
    api/                 HTTP layer only: routes, dependencies, middleware
    core/                config, logging, security, crypto, errors, rate limiting
    db/                  engine/session + Alembic migrations
    models/              SQLAlchemy ORM models
    schemas/             Pydantic request/response models
    services/            business rules (auth, audit, trading control)
    domain/              broker-agnostic vocabulary (TradingMode, AccountEnvironment)
    broker_engine/       BrokerAdapter interface, DTOs, connector registry
  tests/                 pytest suite against a real PostgreSQL database
frontend/                Next.js 16 + TypeScript + Tailwind v4 dashboard
  src/app/               routes (App Router)
  src/components/        shared UI, layout and providers
  src/features/          screen-level feature modules
  src/lib/               API client, types, glossary, pure helpers
docs/                    architecture and developer documentation
```

Future engines (`strategy_engine`, `risk_engine`, `execution_engine`, `market_data`, `backtesting`, `analytics`, `notifications`, `trading_engine`) become sibling packages of `broker_engine` as their phases land. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for why they live in one Python package.

## Everyday commands

```bash
make check     # lint + types + all tests + migration drift check
make test      # backend (pytest) + frontend (vitest)
make build     # production frontend build
```

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Setup](docs/SETUP.md) · [Development](docs/DEVELOPMENT.md) · [Database](docs/DATABASE.md) · [Brokers](docs/BROKERS.md) · [Strategies](docs/STRATEGIES.md) · [Risk engine](docs/RISK_ENGINE.md) · [Backtesting](docs/BACKTESTING.md) · [Security](docs/SECURITY.md) · [Deployment](docs/DEPLOYMENT.md) · [Roadmap](docs/ROADMAP.md)

## Safety principles (non-negotiable)

1. Strategies propose. The **risk engine decides**. No code path bypasses it.
2. The kill switch starts **engaged**. Stopping is one click; resuming is deliberate.
3. **LIVE is hard-locked** by server config and also needs a password plus a typed confirmation. The system never silently switches from demo to live.
4. When state is uncertain (for example, an order outcome is unknown), the **safest outcome wins**. Reconcile before retrying.
5. Nothing fake: no invented balances, trades or broker connections. Sample data, when it exists, is labelled.
6. Past performance never guarantees future results.

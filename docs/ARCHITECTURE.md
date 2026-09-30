# Architecture

## System overview

```
Browser ─► Next.js (frontend/) ─ /api/v1/* rewrite ─► FastAPI (backend/) ─► MySQL 8
            UI only; SSE for live updates              services + engines
                                                          │
                                                          ├─► PaperBroker (in-process simulator)
                                                          └─► MT5BridgeAdapter ─HTTPS/HMAC─► mt5_bridge (Windows) ─► MT5 terminal ─► broker
```

* The browser only talks to the Next.js origin. Session cookies are first-party and `SameSite=Strict`, and the backend address never reaches the browser.
* One backend process serves the API **and** runs the trading engine on background threads. A database lease guarantees that only one engine instance trades, even if several API processes run.
* **All business rules live in the backend.** React renders state and calls the API.

## The pipeline (identical for paper, demo and — later — live)

```
                   ┌──────────────────── engine tick (every ENGINE_TICK_SECONDS) ───────────────────┐
broker.advance() → reconcile orders & positions → sync account/snapshots → [kill switch?] →
  for each ENABLED assignment with a newly closed entry bar:
    candles (closed only) → validate → strategy.evaluate → StrategyEvaluation (why / why not)
      → Signal (unique per assignment+bar+side) → risk_engine.evaluate → APPROVED / REJECTED (+reason)
        → execution_engine.submit_entry → Order (persisted BEFORE send) → broker → fill / reject / UNKNOWN
          → Trade (position) → … → exit detected by reconciliation → Trade closed → journal, notifications
```

Every step writes to the **journal** (`trade_events`) under one correlation ID. The dashboard's trade drawer shows the whole chain.

## Packages (`backend/src/fxrobot/`)

| Package | Responsibility | Never |
|---|---|---|
| `domain` | Broker-neutral types: modes, environments, market DTOs, lifecycle enums | depends on anything |
| `market_data` | Sessions, conversion, pip values, resampling, validation, candle store, CSV, synthetic | fabricate data unlabelled |
| `strategy_engine` | `Strategy` contract, indicators, views (`StaticView`, look-ahead-safe `CursorView`), Trend Pullback V1 | place orders or know the broker |
| `risk_engine` | Pure rules + position sizing; `RiskLimits` | be bypassed |
| `broker_engine` | `BrokerAdapter` contract, error taxonomy, registry, factory, `BrokerManager`, adapters | leak broker types upward |
| `execution_engine` | Idempotent submission, reconciliation, journal | resend an uncertain order |
| `trading_engine` | Per-account runner, risk-context builder, supervisor (lease, heartbeat, worker threads) | trade while the kill switch is engaged |
| `backtesting` | Event-driven backtester (same strategy + risk code), validation service | use unclosed data |
| `analytics` | Metrics shared by backtests and live analytics | invent numbers |
| `notifications` | In-app notifications + `NotificationChannel` interface | break trading if a channel fails |
| `services` | Business operations used by routes (auth, brokers, strategies, risk profiles, market data, trading ops, readiness, analytics) | — |
| `api` | Thin routes, dependencies, serializers, SSE stream | contain business logic |

### Dependency direction

```
api → services → trading_engine → execution_engine → broker_engine → domain
                     │                 └→ risk_engine → strategy_engine → market_data → domain
                     └→ backtesting (uses strategy_engine + risk_engine directly)
core (config, logging, security, crypto, events) is used everywhere
```

## Key design decisions

| Decision | Why |
|---|---|
| **Synchronous adapters + worker threads** | The MetaTrader5 library, SQLAlchemy sessions and the backtester are synchronous. Each account ticks on its own thread, with a timeout |
| **MT5 via a Windows bridge** | The MT5 Python package only runs on Windows next to the terminal. The backend stays portable, and the bridge exposes only the adapter's operations |
| **One Python package, strict subpackages** | One import root and one dependency set. Boundaries are enforced by the dependency direction above |
| **UTC everywhere** | MySQL `DATETIME(6)` stores naive UTC through `UTCDateTime`; sessions force `time_zone='+00:00'`. Broker server time is converted in the bridge |
| **Decimal for money and prices** | No binary floating-point drift. Indicators use numpy floats, and results are quantized back |
| **Server-Sent Events** for live updates | Simple, one-directional, works through the Next.js proxy with cookie auth. REST stays the source of truth |
| **Paper time never runs ahead of real time** | Simulated timestamps stay in the past, so journals and analytics stay coherent |
| **READ COMMITTED isolation** | Long-running engine loops always see fresh rows |

## Real-time updates

`GET /api/v1/stream` (SSE) publishes these topics: `status`, `broker`, `account`, `journal`, `evaluation`, `notification` and `notification_read`. The in-process `EventBus` is thread-safe, and slow subscribers drop old events rather than block the engine. The frontend has a single `StreamProvider`, and pages refetch (debounced) when relevant topics arrive. Only the Markets price table also refreshes every 5 s.

## Frontend

```
src/app/(dashboard)/<page>/page.tsx  thin route → features/<area>/*Screen.tsx
src/features/                        screens: overview, markets, strategies, backtesting, trading,
                                     records (positions/orders/history/journal), brokers, analytics,
                                     risk, notifications, settings, shared (account picker, trade drawer)
src/components/ui                    design system (Card, DataTable, Dialog, Fields, Badge, Term, Meter…)
src/components/charts                lightweight-charts time series & candles, SVG bar chart
src/components/providers             Session, SystemStatus, Stream
src/lib                              typed API client, types, formatters, glossary, hooks
```

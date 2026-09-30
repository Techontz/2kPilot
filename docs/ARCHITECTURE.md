# Architecture

## System overview

```
Browser ──► Next.js (frontend/) ──/api/v1/* rewrite──► FastAPI (backend/) ──► PostgreSQL
             UI only, no trading logic                  services + engines
                                                               │
                                                               ▼
                                                       BrokerAdapter ──► MetaTrader 5 (Phase 2)
```

* The browser only talks to the Next.js origin. Next.js rewrites `/api/v1/*` to the backend, so session cookies are first-party and `SameSite=Strict`, and the backend address never reaches the browser.
* The **backend owns all business rules**. React components render state and call the API. They never decide whether a trade is allowed.

## The trading pipeline (target design)

```
Market Data ─► Strategy Engine ─► Signal ─► Risk Engine ─► Execution Engine ─► BrokerAdapter ─► Broker
                 (proposes)                  (decides)       (idempotent submit,
                                                              reconciliation)
```

Every hop is logged under one correlation ID, so any trade can be traced from signal to exit.

| Stage | Package (planned) | Responsibility | Must never |
|---|---|---|---|
| Market data | `market_data` | candles, ticks, symbols, validation, staleness | fabricate data |
| Strategy | `strategy_engine` | produce `Signal` intentions from data + params | place orders, know about MT5 |
| Risk | `risk_engine` | approve / reject with a stored reason | be bypassed |
| Execution | `execution_engine` | validation, idempotent submit, retries only when safe, reconciliation | assume a failed request means "not executed" |
| Broker | `broker_engine` | translate to/from a specific broker | leak broker types upward |
| Orchestration | `trading_engine` | schedules the pipeline per account, and honours the kill switch | run while the kill switch is engaged |

## Why one Python package instead of top-level folders per engine

The brief suggested top-level `trading_engine/`, `risk_engine/` and so on. Those engines are subpackages of a single installable package, `fxrobot`, instead:

* One import root and one dependency set. Nothing is broken by `sys.path` hacks between sibling top-level folders.
* Boundaries are still strict. Each engine is its own package, with its public API exported from `__init__.py`. Dependency direction is one-way, as the rules below describe.
* An engine can later be split into its own service (for example, a Windows-hosted MT5 bridge) because it only exposes interfaces and DTOs.

### Dependency rules

```
api ──► services ──► engines (risk, execution, …) ──► broker_engine ──► domain
  └──► schemas          └──► models/db                                  ▲
core is used by everyone; domain depends on nothing.                    │
strategy_engine ──► domain + market-data DTOs only (never broker_engine adapters)
```

* `api/` holds routes. They validate input, call a service, and shape output. There is no business logic in them.
* `services/` holds business rules and transactions. Every state change that matters is audited here.
* `domain/` holds broker-agnostic enums and value types, such as `TradingMode` and `AccountEnvironment`.
* `core/` holds infrastructure: config, logging, security, crypto and errors.

## Key Phase 1 components

| Component | File | Notes |
|---|---|---|
| App factory | `backend/src/fxrobot/main.py` | `create_app(settings)`, injectable settings for tests |
| Config | `core/config.py` | Pydantic settings. Production refuses insecure cookies or a missing encryption key |
| Logging | `core/logging.py` | JSON or console output. Correlation ID on every line. Sensitive keys and inline `password=` are masked |
| Correlation IDs | `api/middleware.py` | Accepts a safe `X-Request-ID` or generates one, and echoes it in responses and in audit rows |
| Auth | `services/auth.py` | Opaque session tokens (SHA-256 hash stored), idle and absolute expiry, CSRF token per session |
| Trading control | `services/trading_control.py` | Kill switch and mode rules. This is the single source of `new_orders_permitted` |
| Audit | `services/audit.py` + DB trigger | Append-only, with masked details |
| Broker interface | `broker_engine/interface.py` | Async `BrokerAdapter` ABC. `Decimal` DTOs in `models.py` |
| Connector registry | `broker_engine/registry.py` | Reports connection types honestly (`planned`, `unavailable` or `available`) |

## Frontend structure

```
src/app/(dashboard)/…     one thin page.tsx per route, rendering a feature screen
src/features/<area>/      screen components for that area
src/components/ui/        design-system primitives (Card, Badge, Button, Term, ConfirmDialog…)
src/components/layout/    AppShell, Sidebar, TopBar, LiveBanner, KillSwitchButton
src/components/providers/ SessionProvider, SystemStatusProvider
src/lib/                  api client, types (mirroring backend schemas), glossary, pure helpers
src/proxy.ts              optimistic redirect to /login (the real auth is the backend)
```

* **Status freshness:** `SystemStatusProvider` refetches on window focus and every 30 s. That is one lightweight endpoint, not every endpoint. When the trading engine lands (Phase 7), this is replaced by a WebSocket push channel for prices, positions, order status and risk alerts.

## Real-time updates (planned)

A single authenticated WebSocket (`/api/v1/stream`) will carry typed events: `status`, `quote`, `position`, `order`, `risk_alert` and `broker_connection`. Clients subscribe per topic. REST remains the source of truth, and the stream only pushes changes.

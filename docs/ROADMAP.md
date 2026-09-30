# Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 Foundation | Repo, FastAPI, PostgreSQL + Alembic, auth, logging, config, health checks, audit log, kill switch and modes, LIVE hard lock, broker interface, dashboard foundation, docs | ✅ Done |
| 2 Broker engine | MT5 adapter (Windows host or bridge), connection test, account info, Demo/Live detection, symbols, quotes, candles, positions, orders. Encrypted `broker_connections` / `trading_accounts`. Add Broker UI | Next |
| 3 Market data | Symbol metadata, historical candle download and storage, validation (gaps, duplicates, spikes), timeframe handling, staleness detection | |
| 4 Strategy engine | Strategy interface, `Signal` model, Trend Pullback V1, parameter schemas, versioning, assignment and enable flow | |
| 5 Risk engine | Per-trade rules and position sizing (see RISK_ENGINE.md), risk profiles, violation log, Risk screen configuration | |
| 6 Backtesting | Event-driven simulator sharing strategy and risk code, cost model, metrics, IS/OOS and walk-forward, results UI | |
| 7 Demo trading | Trading engine orchestration, execution engine (idempotency, reconciliation), journal, notifications, WebSocket stream | |
| 8 Dashboard & analytics | Equity and drawdown charts, strategy/instrument/session analytics, execution quality | |
| 9 Reliability | Restart recovery, reconciliation on boot, metrics (Prometheus/OpenTelemetry), Redis rate limiting, security hardening (MFA, nonce CSP) | |
| 10 Live readiness | Deliberate review: out-of-sample and demo results, risk config, execution reliability, broker behaviour, operational safeguards. **Only then** may `LIVE_TRADING_ENABLED` be considered | |

## Known technical debt and follow-ups

* Status refresh polls one endpoint every 30 s. It will be replaced by the WebSocket stream in Phase 7.
* The login rate limiter is in-process. Move it to Redis before horizontal scaling.
* The Docker setup hasn't been run in CI yet. Add a CI workflow (GitHub Actions: Postgres service, `make check`, `docker build`).
* `starlette.testclient` warns that `httpx` is deprecated in favour of `httpx2`. Migrate when stable.

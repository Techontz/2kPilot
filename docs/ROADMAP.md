# Roadmap & live readiness

## Status

| Phase | Scope | Status |
|---|---|---|
| Foundation | FastAPI, auth, audit, config, logging, health | ✅ |
| Database | MySQL 8 migration (baseline + trading schema), triggers, strict sessions | ✅ |
| Broker engine | Adapter contract, error taxonomy, manager (reconnect, status, notifications), registry | ✅ |
| MT5 | Windows `mt5_bridge` + backend client, contract-tested | ✅ code — ⏳ **needs a real Windows MT5 terminal** |
| Paper broker | Full simulator, synthetic and replay markets | ✅ |
| Market data | Symbols, quotes, candles, validation, sessions, CSV/MT5/synthetic datasets | ✅ |
| Strategy engine | Contract, explainable evaluations, Trend Pullback V1, versions, assignments | ✅ |
| Risk engine | 20 rules, sizing, profiles, account halts | ✅ |
| Backtesting | Realistic costs, no look-ahead, in/out-of-sample, walk-forward, sensitivity | ✅ |
| Execution | Idempotency, reconciliation, restart recovery, external positions | ✅ |
| Trading engine | Per-account runners, lease, heartbeat, kill switch | ✅ |
| Journal, analytics, notifications | Full lifecycle, stored-data analytics, in-app alerts + channel interface | ✅ |
| Dashboard | 14 pages, wizard, live updates, responsive, glossary | ✅ |
| Live readiness | Checklist per account | ✅ checklist — 🔒 LIVE stays locked |

## Live readiness

LIVE is impossible while `LIVE_TRADING_ENABLED=false`. Brokers → an account → **LIVE readiness checklist** gathers the evidence for a deliberate human review:

* The broker is connected and the account is recognised as LIVE by the broker.
* A risk profile is configured.
* The kill switch has been exercised.
* A strategy is configured.
* **Out-of-sample validation on real (non-synthetic) data**: at least 30 trades with positive expectancy.
* **Broker DEMO track record**: at least 30 closed demo trades over at least 28 days.
* Market data is fresh; the execution path is healthy (no unresolved orders, failure rate under 10 %); the engine is running.
* **MFA for the owner.** Not implemented yet, so the checklist can't pass today, by design.

Passing every check still doesn't unlock anything. An operator must change the server setting after reviewing the evidence.

## What still needs your hardware or credentials

1. A Windows PC or VPS with MetaTrader 5 and a **demo** account → run `mt5_bridge` ([MT5_BRIDGE_SETUP.md](MT5_BRIDGE_SETUP.md)).
2. Real historical data (an MT5 export or download) for meaningful backtests.
3. Weeks of broker-demo trading before anyone considers live.

## Known limitations and next steps

* **MFA** (TOTP) for the owner is required before live.
* A real-terminal soak test of the bridge: reconnects, weekend offsets, broker-specific filling modes and symbol suffixes.
* Backtests support USD accounts on USD pairs; crosses need a second price series for conversion.
* Paper symbols are limited to the six synthetic FX majors (replay uses the same specifications).
* No news calendar yet (news blackout is a planned risk rule).
* The event stream and login rate limiter are in-process (single API process). Move them to Redis to scale out.
* The Docker Compose setup has not been run; there is no CI workflow yet (suggested: GitHub Actions with a MySQL 8 service running `make check` and `make e2e`).
* Additional notification channels (email/Telegram) can plug into `NotificationChannel`.

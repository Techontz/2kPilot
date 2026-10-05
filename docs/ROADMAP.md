# Roadmap & live readiness

| Area | Status |
|---|---|
| Laravel backend (auth, MFA, policies, audit, API, jobs, scheduler) | ✅ done |
| Next.js dashboard (all pages, Add Broker wizard, Trade page) | ✅ done |
| Paper trading end to end | ✅ verified in a real browser |
| Risk engine (all requested controls) | ✅ |
| Backtesting (single, in/out-of-sample, walk-forward, sensitivity) | ✅ |
| Deriv adapter (official 2026 API) | ✅ code, offline-verified — ⏳ **needs your Deriv App ID + token** for a live demo test |
| MT5 | ✅ code, contract-tested — ⏳ **needs your Windows PC/VPS + MT5 demo login** |
| Pending (limit/stop) entries for manual tickets | ⏳ planned (Deriv doesn't offer them; MT5/paper do) |
| Email/Telegram notification channels | ⏳ planned (`NotificationChannel` interface exists) |

## Before any real money

1. Run a strategy on PAPER, then on a broker **DEMO** account for at least 4 weeks and 30+ trades.
2. Compare demo results with an out-of-sample backtest of the same version.
3. Review the journal for rejected signals, slippage and reconciliation events.
4. Turn on MFA. Only then consider `LIVE_TRADING_ENABLED=true` — with the smallest risk profile.

Nothing in this project claims that any strategy is profitable.

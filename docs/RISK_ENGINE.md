# Risk engine

The risk engine is the final authority. `risk_engine.evaluate(signal, context, limits)` is a **pure function** used by live trading and by backtests alike. Every rule's result is stored on the signal (`risk_checks`). Any failure rejects the trade with a reason such as *"Trade rejected: Daily loss limit: loss 2.01% reached limit 2.00%"*. A rule that cannot be evaluated because of malformed input **fails** rather than crashing.

## Global gates (`services/trading_control.py`)

```
new_orders_permitted = kill switch released
                     AND engine running (fresh heartbeat)
                     AND NOT (mode == LIVE AND LIVE_TRADING_ENABLED == false)
                     AND mode != BACKTEST
```

* A fresh install is **DEMO with the kill switch engaged**.
* The kill switch is one click, idempotent and audited. It stops strategy evaluation and new orders. **It never closes positions.**
* **Emergency stop** engages the kill switch and, *only if chosen*, closes every open position at market (audited).
* The mode can change only while stopped. LIVE additionally needs the server hard lock off, your password, and the phrase `ENABLE LIVE TRADING`.
* Account environment vs mode: DEMO mode allows PAPER and DEMO accounts; LIVE mode also allows LIVE accounts; UNKNOWN accounts **never** trade.

## Per-trade rules (evaluated in order; all recorded)

| # | Rule | Rejects when |
|---|---|---|
| 1 | Kill switch | engaged |
| 2 | Operating mode | account environment not allowed in the current mode, or LIVE account while hard-locked |
| 3 | Account trading enabled | account switched off |
| 4 | Broker connected | disconnected |
| 5 | Stop loss required | missing or on the wrong side (**cannot be disabled**) |
| 6 | Market data fresh | quote older than `max_data_age_seconds`, or the signal bar closed more than half a bar ago |
| 7 | Market open | weekend closure |
| 8 | Trading session | session not in `allowed_sessions` (ASIA / LONDON / OVERLAP / NEW_YORK) |
| 9 | Spread | above `max_spread_pips` |
| 10 | Stop distance | outside `min_stop_pips … max_stop_pips` |
| 11 | Reward/risk | below `min_reward_risk`, or no take profit when a minimum is set |
| 12 | Daily loss limit | realised today + open P/L ≥ `max_daily_loss_pct` of start-of-day balance |
| 13 | Weekly loss limit | same, per ISO week |
| 14 | Max drawdown | equity ≥ `max_drawdown_pct` below its peak → **account trading is disabled** until reviewed |
| 15 | Loss cooldown | `cooldown_after_losses` consecutive losses, paused for `cooldown_minutes` |
| 16 | Trades per day | `max_trades_per_day` reached |
| 17 | Open positions | `max_open_positions` or `max_positions_per_symbol` reached |
| 18 | Position size | risk budget buys less than the broker minimum volume (never rounded **up**) |
| 19 | Total exposure | total lots > `max_total_exposure_lots`, or total open risk > `max_total_risk_pct`, or **any open position has unknown risk** (e.g. opened outside 2kFX) |
| 20 | Margin | estimated margin > free margin, or the base currency can't be valued |

## Position sizing

```
budget      = equity × risk_per_trade_pct / 100
loss/lot    = stop distance in points × value of 1 point for 1 lot (account currency)
volume      = floor(budget / loss_per_lot, broker volume step)  → capped by max_position_lots and broker max
```

The point value comes from the broker (MT5 `tick_value`) or is converted from quotes (direct, inverse or USD cross). If no rate is available, the trade is rejected. Approved decisions also carry `max_slippage_points` (from `max_slippage_pips`), which is sent to the broker as the maximum deviation.

## Uncertainty rules

* An account with any order in `PENDING_SUBMIT`, `SUBMITTED` or `UNKNOWN` takes **no new entries** until reconciliation resolves it.
* Malformed candles skip evaluation, with a notification. A missing latest bar is never evaluated late.
* Positions opened outside 2kFX have unknown risk, so they block new entries until closed.

## Profiles

`risk_profiles` hold typed limits; each account uses one. `NULL` disables an optional limit; `risk_per_trade_pct`, `max_data_age_seconds` and `allowed_sessions` are mandatory. The default profile *Conservative (default)* is 0.5 % per trade, 2 % daily, 4 % weekly, 10 % drawdown, 3 positions, 1 per symbol, spread ≤ 2.5 pips, stop 8–150 pips, RR ≥ 1.5, London/Overlap/New York sessions, and a 240-minute cooldown after 3 losses. Every change is audited.

Tests: `tests/test_risk_engine.py` (100 cases, one per condition) and the pipeline and reliability suites.

# Risk engine

The risk engine is the final authority. `risk_engine.evaluate(signal, context, limits)` is a **pure function** used by live trading and by backtests alike. The `RiskContext` carries the account owner's controls (mode, STOP switch, LIVE authorisation), the platform halt and the server LIVE lock. Every rule's result is stored on the signal (`risk_checks`). Any failure rejects the trade with a reason such as *"Trade rejected: Daily loss limit: loss 2.01% reached limit 2.00%"*. A rule that cannot be evaluated because of malformed input **fails** rather than crashing.

## Trading controls (Laravel `app/Services/Trading/TradingControl.php`; the engine reads them every tick)

Each user has their own STOP switch and operating mode (`user_trading_states`); admins have a platform-wide halt (`system_state`).

```
account may open trades = platform not halted (admin)
                        AND the account owner's STOP switch released
                        AND environment fits the owner's mode
                        AND (LIVE account → LIVE_TRADING_ENABLED == true AND owner's LIVE
                             authorisation covers THIS account with its current risk profile)
                        AND account trading enabled AND a risk profile assigned
                        AND engine running (fresh heartbeat)
```

Otherwise the engine only monitors the account (sync, reconcile).

* A new user starts in **DEMO with trading stopped**.
* STOP TRADING is one click, idempotent and audited. It stops strategy evaluation and new orders on **your** accounts. **It never closes positions.**
* **Close positions** (a separate action) stops your trading and then closes every open position on your accounts at market (audited).
* **Platform halt** (admins: `POST /api/admin/halt`, `POST /api/admin/resume`): while halted nobody trades; users' own switches are left as they were.
* The mode can change only while your trading is stopped. LIVE additionally needs the server hard lock off, **MFA**, your password, the phrase `ENABLE LIVE TRADING`, and one of your LIVE accounts with a risk profile; the authorisation time and a snapshot of that profile's limits are recorded. Switching back to DEMO clears the authorisation.
* **Manual tickets** (Trade page) run through exactly the same rules; they validate the chosen volume against the per-trade budget instead of computing it, and need a fresh price (no signal-bar age).
* Account environment vs mode: DEMO mode trades PAPER and DEMO accounts; LIVE mode trades **LIVE accounts only**; UNKNOWN accounts **never** trade.

## Per-trade rules (evaluated in order; all recorded)

| # | Rule | Rejects when |
|---|---|---|
| 1 | Kill switch | the owner's STOP switch is engaged, or the platform is halted |
| 1b | Strategy enabled | an administrator stopped new entries from the signal's strategy (or the built-in it was copied from) — *"new entries from … are stopped by an administrator: <reason>"*. Never closes positions |
| 2 | Operating mode | account environment not allowed in the owner's mode, or LIVE account while hard-locked or without the owner's LIVE authorisation. The engine binds the authorisation: the account must be `live_authorized_account_id`, its risk profile must be `live_authorized_profile_id`, and that profile must not have been edited after `live_authorized_at` — otherwise *"Real-money authorization doesn't cover this account/limits — re-authorize"* |
| 3 | Account trading enabled | account switched off |
| 4 | Broker connected | disconnected |
| 4b | Contract supported | the contract spec cannot be traded here, with the reason: Deriv + SPOT ("Deriv accounts trade contracts…"), a family/duration/multiplier the broker does not offer on the symbol (from `contracts_for`), or invalid settings |
| 5 | Stop loss required | missing or on the wrong side (**cannot be disabled**). For contracts it passes as *bounded*: a Rise/Fall can lose at most its stake, and Deriv stops a Multiplier out before its loss exceeds the stake |
| 6 | Market data fresh | quote older than `max_data_age_seconds`, or the signal bar closed more than half a bar ago |
| 7 | Market open | the broker says the market is closed (Deriv `exchange_is_open`) or trading is suspended (`is_trading_suspended`), otherwise the FX weekend |
| 8 | Trading session | session not in `allowed_sessions` (ASIA / LONDON / OVERLAP / NEW_YORK) |
| 8b | Trading hours | outside the optional `trading_hours_start`–`trading_hours_end` UTC window (may wrap midnight) |
| 9 | Spread | above `max_spread_pips` |
| 10 | Stop distance | outside `min_stop_pips … max_stop_pips` (SPOT only; *not applicable* for contracts) |
| 11 | Reward/risk | below `min_reward_risk`, or no take profit when a minimum is set (SPOT only) |
| 12 | Daily loss limit | realised today + open P/L ≥ `max_daily_loss_pct` of start-of-day balance |
| 13 | Weekly loss limit | same, per ISO week |
| 14a | Minimum balance | optional `min_account_balance`: the balance is below it (or unknown) |
| 14 | Max drawdown | equity ≥ `max_drawdown_pct` below its peak → **account trading is disabled** until reviewed |
| 14b | Settled P/L | a closed trade on the account has no confirmed P/L yet (the broker's history lagged) — the loss limits cannot see it, so new entries wait until reconciliation settles it |
| 15 | Loss cooldown | `cooldown_after_losses` consecutive losses, paused for `cooldown_minutes` |
| 15b | Losing streak | `max_consecutive_losses` losses in a row **among today's (UTC) closed trades** — no new trades until 00:00 UTC |
| 15c | Daily loss amount | money lost today (realised + open P/L) ≥ `max_daily_loss_amount`; for a contract also when the worst case — every open contract losing its whole stake (`risk_amount`), then this stake too — would take today's loss past the limit (an open position with unknown risk fails it) |
| 15d | Daily profit target | realised P/L today ≥ `daily_profit_target_amount` — stop for the day |
| 16 | Trades per day | `max_trades_per_day` reached |
| 17 | Open positions | `max_open_positions` or `max_positions_per_symbol` reached |
| 18c | Stake (contracts) | stake above `max_stake_amount`, above the balance, above the per-trade budget `risk_per_trade_pct` × balance (refused, never shrunk), a Multiplier `stop_loss_amount` above the stake, outside the **broker's** stake range (`validation_params.stake.min/max` from a live `proposal` — **fails closed** when the broker reports no limits) |
| 18d | Stop/target amounts (Multipliers) | the money amounts the Multiplier will be bought with — the assignment's own, or the strategy's stop/target prices converted from the current price exactly as the adapter does — fall outside the broker's `validation_params.stop_loss` / `take_profit` range (Deriv R_10/R_25, 1.00 stake: stop 0.10–1.00, target 0.10–50.00). A stop beyond the stake is left to the broker's stop out (loss bounded by the stake). When the broker does not report the range the rule passes and says so — the broker refuses out-of-range amounts before anything is bought |
| 18 | Position size | risk budget buys less than the broker minimum volume (never rounded **up**); manual: volume off-step, outside broker range, above `max_position_lots`, or risking more than the budget |
| 18b | Symbol exposure | lots on this symbol after the trade > `max_symbol_exposure_lots` |
| 19 | Total exposure | total lots > `max_total_exposure_lots`, or total open risk > `max_total_risk_pct`, or **any open position has unknown risk** (e.g. opened outside 2kPilot) |
| 20 | Margin | estimated margin > free margin, or the base currency can't be valued |

## Position sizing

### Contracts (Rise/Fall, Multipliers)

```
stake  = the assignment's stake, or the risk profile's stake_amount
volume = 1 contract;  risk_amount = stake  (the most it can lose)
```

The stake must pass rule 18c — including the per-trade budget: the stake is the most the contract can lose, so it may not exceed `risk_per_trade_pct` × balance (Beginner: 0.5 %, so a 1.00 stake needs a balance of at least 200; a 10 000 demo account allows up to 50). Open risk (open stakes/risks + this stake) is still capped by `max_total_risk_pct`. Lot exposure and margin do not apply. Rules 15b–15d apply to SPOT trades too.

### SPOT (lots, Paper)

```
budget      = equity × risk_per_trade_pct / 100
loss/lot    = stop distance in points × value of 1 point for 1 lot (account currency)
volume      = floor(budget / loss_per_lot, broker volume step)  → capped by max_position_lots and broker max
```

The point value comes from the broker when it reports one, or is converted from quotes (direct, inverse or USD cross). If no rate is available, the trade is rejected. Approved decisions also carry `max_slippage_points` (from `max_slippage_pips`), which is sent to the broker as the maximum deviation.

### Strategy risk caps

A strategy may declare caps (`Strategy.risk_caps`; Adaptive Trend & Momentum: 0.5 % per trade, 2 % daily loss, 1 open position). Live and in backtests they are applied with `RiskLimits.tightened()`: the smaller of the profile's value and the cap wins, a disabled limit takes the cap, nothing is ever loosened. For contracts the stake is the maximum loss, so with 0.5 % per trade a 1.00 stake needs a balance of at least 200.

Never implemented, by design: martingale, doubling after losses, recovery or revenge trading, increasing size after losses, or any guaranteed-profit logic.

## Uncertainty rules

* An account with any order in `PENDING_SUBMIT`, `SUBMITTED` or `UNKNOWN` takes **no new entries** until reconciliation resolves it.
* Malformed candles skip evaluation, with a notification. A missing latest bar is never evaluated late.
* Positions opened outside 2kPilot have unknown risk, so they block new entries until closed.
* A trade closed while the broker's history has no closing deal yet keeps `net_pnl` NULL (P/L pending); reconciliation re-reads the history (every 30 s) until it is settled, and until then it blocks new entries (rule 14b).

## Profiles

`risk_profiles` hold typed limits and belong to a user; each account uses one of its owner's profiles. `NULL` disables an optional limit; `risk_per_trade_pct`, `max_data_age_seconds`, `allowed_sessions` and `stake_amount` are mandatory. Every new user gets a *Beginner* profile: 0.5 % per trade, 2 % daily, 4 % weekly, 10 % drawdown, 3 positions, 1 per symbol, 20 trades a day, spread ≤ 2.5 pips, stop 8–150 pips, RR ≥ 1.5, London/Overlap/New York sessions, a 240-minute cooldown after 3 losses — and for contracts a **1.00 stake** (maximum 5.00; with 0.5 % per trade a stake must also fit 0.5 % of the balance: 1.00 needs ≥ 200, 5.00 needs ≥ 1 000), trading halted for the rest of the UTC day after **3 losses in a row**, no money loss limit or profit target (optional). Every change is audited. `min_account_balance` (optional, added by migration `2026_10_11_000100`) is off by default.

Tests: `trading-engine/tests/test_risk_engine.py` (107 cases), `test_manual_orders.py`, and the pipeline and reliability suites. Risk profiles are edited in Laravel with the same validation (`app/Http/Requests/RiskProfileRequest.php`).

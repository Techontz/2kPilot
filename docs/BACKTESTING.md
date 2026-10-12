# Backtesting

The goal is to find out honestly whether a strategy has an edge **after costs**, and to make overfitting visible.

## How a run happens

Backtesting page → Laravel validates and asks the engine to create the run (`QUEUED`) → a Laravel **queue job** (`RunBacktest`, on the `backtests` Horizon queue) asks the engine to execute it → results are stored in `backtests` / `backtest_trades` and shown on the report page (which refreshes while it runs).

## Engine (`trading-engine/src/fxrobot/backtesting/engine.py`)

* **Same code as live.** It uses the same `Strategy.evaluate` and the same `risk_engine.evaluate` (every rule, sizing included) as the trading engine.
* **Closed bars only.** `CursorView` reveals a bar only once `open + timeframe ≤ now`. Higher timeframes are resampled from the base data and appear only after their period ends.
* **Next-bar fills.** A signal at a bar close fills at the **next** base bar's open, plus spread and slippage. A signal on the final bar is dropped. If the price gapped past the stop before entry, the trade is skipped.
* **Strategy exits.** A rule set's exit conditions (`close_buy_when` / `close_sell_when`) are checked on every entry-timeframe close while a Spot or Multiplier trade is open; when they hold, the trade closes at the **next bar's open** (`STRATEGY`, with spread and slippage for Spot; Multipliers are sold, outcome `SOLD`). Rise/Fall contracts always run to expiry. `metrics.strategy_exits` counts them.
* **Exits.** They are checked on every base bar. If a bar touches both SL and TP, the **stop** is assumed. Gaps through a stop fill at the (worse) open. Anything still open at the end closes as `END_OF_TEST`.
* **Costs.**
  * Spread: each bar's recorded spread, a fixed override, or a 1.0-pip fallback.
  * Adverse slippage on entries and stop exits.
  * Commission per lot per side.
  * Optional swap per lot at the 21:00 UTC rollover.
* **Currency.** USD accounts on USD pairs (EURUSD, GBPUSD, AUDUSD, USDJPY, USDCHF, USDCAD) and USD-quoted synthetic indices (R_10 … R_100, 1HZ…).
* **Reproducibility.** Every run stores the strategy and code version, parameters, risk settings, cost model, dataset ID and a **data checksum**.

### Contracts (Rise/Fall, Multipliers)

A backtest can trade the same contract spec as an assignment (`contract`), with two extra inputs: `payout_ratio` (Rise/Fall profit per 1 of stake when won, default **0.95**) and `commission_pct` (Multipliers, % of stake × multiplier, default 0).

* **Rise/Fall**: entry at the next bar's open after the signal; exit = **close of the bar at entry + duration**, the duration converted to bars of the dataset timeframe (rounded up, with a note, when it is not a whole number of bars). Won → +stake × payout_ratio; lost → −stake; **equal prices lose CALL/PUT** and win CALLE/PUTE.
* **Durations candles cannot resolve are refused**: tick durations, and any duration shorter than one bar ("A 5m Rise/Fall is shorter than one H1 candle…"). Tick datasets are not built yet.
* **Multiplier**: P/L = stake × multiplier × (exit ÷ entry − 1) × direction − commission, never below −stake (stop out). As on Deriv, the stop loss and stop out act on the profit **net of commission**. The risk engine's *Stop/target amounts* rule runs in backtests too; `BacktestConfig.stop_loss_min` / `take_profit_min` / `take_profit_max` simulate the broker's range (the real-data evaluation used Deriv's reported 0.10 / 0.10 / 50.00 for a 1.00 stake). Take-profit / stop-loss **money amounts** (or the strategy's price levels converted, as live) close the trade intra-bar from the bar's high/low; if a bar touches both, the **stop** is assumed; a gap through the stop fills at the open (still capped at the stake).
* The stake and the money limits — losing streak (per UTC day), daily loss amount, daily profit target, trades per day — come from the **same risk engine** as live trading (broker stake range simulated as 0.01–100,000). One contract is held at a time.
* A Rise/Fall still open when the data ends is left out (noted); a Multiplier is closed at the last close (`END_OF_TEST`).
* **The payout is an estimate.** Live payouts vary with every proposal and include up to 3 % app markup, so results carry `payout_ratio_is_estimate: true`, a warning and a note. Compare with a few real demo proposals before trusting a Rise/Fall result.
* Synthetic indices: datasets for R_10 … R_100 (and other Deriv symbols such as 1HZ100V) can be **downloaded from a Deriv connection** (`ticks_history`, style `candles`) or generated SYNTHETIC by 2kPilot; they are treated as 24/7 instruments quoted in USD.

Use a data timeframe equal to or finer than the strategy's entry timeframe. H1 data works for Trend Pullback, and M15 data gives more precise exits.

## Validation modes

| Mode | What it does | Report |
|---|---|---|
| Single | One run | Metrics, curves, breakdowns, trade list |
| **In/out of sample** | Splits the range (default 70/30). The out-of-sample part is never used to choose anything | Side-by-side table; warns if the edge disappears or profit factor drops more than 30 % |
| Walk-forward | Rolling windows: choose the best grid value on training months by expectancy (≥10 trades), then test on the next unseen months | Per-window table; the headline metrics are the **stitched out-of-sample** results |
| Sensitivity | Runs a grid of ≤16 combinations over one or two parameters | Table; warns if few combinations are profitable or returns swing wildly |

### The demo-forward-testing gate (`backtesting/validation.py`)

Split and walk-forward reports carry `report.validation` = `{qualifies_for_demo_forward_testing, checks[], reasons[], note}`. It passes only when **all** hold:

1. real market data (synthetic data never qualifies);
2. at least **100 out-of-sample trades**;
3. positive out-of-sample **expectancy per trade after costs**;
4. positive expectancy in **more than half** of the walk-forward folds that traded, with at least 3 such folds (a single split always fails this check: it cannot show stability);
5. the edge is **distinguishable from noise**: the t-statistic of the mean out-of-sample R-multiple (`metrics.expectancy_r_tstat` = mean ÷ standard error) is at least 2. This check was added after the first real-data run, in which R_25 passed checks 1–4 with a near-zero edge — see the results below.

It is informational: **nothing is enabled automatically**, and passing is not a claim of profitability.

Warnings shown on every run where they apply:
* "SYNTHETIC data: these results say nothing about real markets."
* "Historical results do not guarantee future performance."
* "Only N trades — too few for statistical confidence (aim for 30+)."
* "The maximum-drawdown limit halted trading during this test."

## Metrics (`analytics/metrics.py`, shared with live analytics)

* **Results:** net P/L, return %, trade count, wins/losses/breakeven, win rate, average win and loss, largest win and loss; for contracts also `outcomes` (WON/LOST/SOLD counts), `contract`, `payout_ratio` + `payout_ratio_is_estimate`, `notes`.
* **Edge:** expectancy (money and R), profit factor (empty when there are no losses), average R:R.
* **Risk:** max drawdown (amount and %), longest win and loss streaks (`longest_losing_streak`; breakeven trades break a streak), total costs, average holding time.
* **Curves and breakdowns:** equity and drawdown curves, monthly results, and breakdowns by symbol (instrument), session, side, strategy and **market regime at entry** (`by_regime`: TREND_UP, TREND_DOWN, SIDEWAYS, HIGH_VOLATILITY, UNCERTAIN — classified by the strategy's `regime()` on closed bars when the signal was taken, stored per trade in `backtest_trades.regime`). Every breakdown row has trades, win rate, profit factor, expectancy per trade (and in R), average realised reward/risk (`avg_rr` = average win ÷ |average loss|), max drawdown of the slice's own cumulative P/L, longest losing streak and net P/L after costs. A backtest uses one dataset, so results **by instrument** across markets are the latest completed test per symbol (the Strategies page shows them side by side).
* **Diagnostics:** how many signals were rejected, and by which risk rule.

## Look-ahead and leakage tests (`trading-engine/tests/test_backtesting.py`)

* Truncating the data at time T leaves every trade before T unchanged.
* Spiking every candle after T leaves every decision before T unchanged.
* Entries fill at the next bar's open, never the signal bar's close.
* Higher-timeframe bars are visible only after they close; a stub strategy that asks for everything sees only closed bars.
* Determinism: the same inputs give the same trades.
* Cost monotonicity: more spread, commission or slippage always means lower net P/L.

## Data

* **CSV import**: MetaTrader export format or generic OHLC, with a UTC offset for server-time exports. Bad rows are dropped and reported.
* **Download** from one of your connected broker accounts. Deriv history comes from `ticks_history` (candles): the adapter pages **backwards** with `end` (a string) + `count`, because Deriv's servers ignore `start` and reject `adjust_start_time: 0` (checked against the live public API, 2026-10). Deriv serves about **one year** of M1/M5/M15 history; requests before that limit are answered with the latest bars, which ends the paging. The first candle of the window may be partial and unaligned — drop it.
* **Synthetic** ("practice data"): any candle size from M1 to D1, deterministic per seed, labelled SYNTHETIC everywhere. Generated from the same 1-minute feed as Paper accounts (same seed → same prices). Periods are 30–3650 days, capped at **60 days for M1** and **365 days for M5** (≈100k bars at most). The *Test on history* dialog defaults to the strategy's own timeframe.

Datasets and backtests belong to the user who created them (datasets with no owner are shared). Every dataset gets validation: gaps (ignoring weekends), duplicates, bad OHLC and spikes.

## Real-data evaluation of Adaptive Trend & Momentum (2026-10-11)

**Data.** REAL Deriv candles downloaded read-only from the public, unauthenticated WebSocket (`wss://api.derivws.com/trading/v1/options/ws/public`, `ticks_history`, style `candles`; no login, no token, no order). R_10 and R_25, M5 (105,118 / 105,119 bars) and M15 (35,039 each), 2025-10-11 08:35 → 2026-10-11 08:25 UTC — Deriv's whole one-year history. No gaps; the first (partial, unaligned) candle dropped. M15 bars resampled from M5 match Deriv's own M15 bars exactly for 99.6 % (R_10 34,898 / 35,038; R_25 34,953 / 35,038; the rest differ by the last tick at the boundary). Kept in a scratch directory, not in any database.

**Setup.** Default parameters, never tuned on this data (so every walk-forward window is genuinely out of sample; there is no grid). Multiplier, 1.00 stake, the lowest multiplier Deriv offers (R_10 ×400, R_25 ×160), commission as quoted by Deriv (0.02 per contract ⇒ 0.005 % / 0.0125 % of stake × multiplier), Deriv's stop/target ranges (0.10 minimum), stop and stop out net of commission, 1,000 starting balance, the Beginner risk profile (0.5 % per trade, 2 % daily, 3-loss cooldown and daily halt) tightened by the strategy's caps. The engine's own `Backtester`, `walk_forward_windows` (90-day train / 30-day test, 9 folds from 2026-01-12) and `demo_forward_gate`. Two identical runs gave identical results.

| Out of sample (walk-forward, stitched) | R_10 | R_25 | Both |
|---|---|---|---|
| Trades | 609 | 598 | 1,207 |
| Win rate | 33.0 % | 35.3 % | 34.1 % |
| Profit factor | 0.95 | 1.05 | 1.00 |
| Average realised reward/risk (avg win ÷ avg loss) | 1.93 | 1.93 | 1.93 |
| Expectancy per trade after costs (1.00 stake) | −0.01 | +0.01 | −0.00 |
| t-statistic of the mean R | −0.61 | 0.58 | −0.02 |
| Net P/L after costs | −5.80 | +5.54 | −0.26 |
| Max drawdown | 10.77 (1.07 %) | 7.21 (0.72 %) | 14.04 |
| Longest losing streak | 17 | 18 | 17 |
| Folds with positive expectancy | 2 of 9 | 6 of 9 | 8 of 18 |
| **Qualifies for demo forward testing** | **No** | **No** | **No** |

By regime at entry (both markets, out of sample): TREND_DOWN 635 trades, 34.5 % wins, PF 1.01, +1.19; TREND_UP 572 trades, 33.7 % wins, PF 0.99, −1.45 — the strategy only trades in trend regimes, by design. A 70/30 split agrees (out of sample: R_10 236 trades, PF 0.90, −4.30; R_25 225 trades, PF 1.06, +2.36). Full year, single run: R_10 826 trades, PF 0.95, −8.19; R_25 798 trades, PF 1.01, +0.96.

**Reading.** With a 2:1 target the break-even win rate is about 34 %; the strategy wins about 34 %. After costs it is **break-even within noise on both markets** — no evidence of an edge. R_25 alone passed the first four gate checks (sample, positive expectancy, 6 of 9 folds), but its edge (+0.009 R per trade, t = 0.58) is indistinguishable from chance — which is why the fifth check was added. Nothing was enabled. Do not trade it with real money; if anything, watch it on a demo account as a learning exercise only.

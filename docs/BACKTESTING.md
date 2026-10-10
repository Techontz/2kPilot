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
* **Multiplier**: P/L = stake × multiplier × (exit ÷ entry − 1) × direction − commission, never below −stake (stop out). Take-profit / stop-loss **money amounts** (or the strategy's price levels converted, as live) close the trade intra-bar from the bar's high/low; if a bar touches both, the **stop** is assumed; a gap through the stop fills at the open (still capped at the stake).
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

Warnings shown on every run where they apply:
* "SYNTHETIC data: these results say nothing about real markets."
* "Historical results do not guarantee future performance."
* "Only N trades — too few for statistical confidence (aim for 30+)."
* "The maximum-drawdown limit halted trading during this test."

## Metrics (`analytics/metrics.py`, shared with live analytics)

* **Results:** net P/L, return %, trade count, wins/losses/breakeven, win rate, average win and loss, largest win and loss; for contracts also `outcomes` (WON/LOST/SOLD counts), `contract`, `payout_ratio` + `payout_ratio_is_estimate`, `notes`.
* **Edge:** expectancy (money and R), profit factor (empty when there are no losses), average R:R.
* **Risk:** max drawdown (amount and %), longest win and loss streaks (`longest_losing_streak`; breakeven trades break a streak), total costs, average holding time.
* **Curves and breakdowns:** equity and drawdown curves, monthly results, and breakdowns by symbol, session, side and strategy.
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
* **Download** from one of your connected broker accounts.
* **Synthetic** ("practice data"): any candle size from M1 to D1, deterministic per seed, labelled SYNTHETIC everywhere. Generated from the same 1-minute feed as Paper accounts (same seed → same prices). Periods are 30–3650 days, capped at **60 days for M1** and **365 days for M5** (≈100k bars at most). The *Test on history* dialog defaults to the strategy's own timeframe.

Datasets and backtests belong to the user who created them (datasets with no owner are shared). Every dataset gets validation: gaps (ignoring weekends), duplicates, bad OHLC and spikes.

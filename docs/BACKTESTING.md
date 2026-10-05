# Backtesting

The goal is to find out honestly whether a strategy has an edge **after costs**, and to make overfitting visible.

## How a run happens

Backtesting page → Laravel validates and asks the engine to create the run (`QUEUED`) → a Laravel **queue job** (`RunBacktest`) asks the engine to execute it → results are stored in `backtests` / `backtest_trades` and shown on the report page (which refreshes while it runs).

## Engine (`trading-engine/src/fxrobot/backtesting/engine.py`)

* **Same code as live.** It uses the same `Strategy.evaluate` and the same `risk_engine.evaluate` (every rule, sizing included) as the trading engine.
* **Closed bars only.** `CursorView` reveals a bar only once `open + timeframe ≤ now`. Higher timeframes are resampled from the base data and appear only after their period ends.
* **Next-bar fills.** A signal at a bar close fills at the **next** base bar's open, plus spread and slippage. A signal on the final bar is dropped. If the price gapped past the stop before entry, the trade is skipped.
* **Exits.** They are checked on every base bar. If a bar touches both SL and TP, the **stop** is assumed. Gaps through a stop fill at the (worse) open. Anything still open at the end closes as `END_OF_TEST`.
* **Costs.**
  * Spread: each bar's recorded spread, a fixed override, or a 1.0-pip fallback.
  * Adverse slippage on entries and stop exits.
  * Commission per lot per side.
  * Optional swap per lot at the 21:00 UTC rollover.
* **Currency.** USD accounts on USD pairs (EURUSD, GBPUSD, AUDUSD, USDJPY, USDCHF, USDCAD).
* **Reproducibility.** Every run stores the strategy and code version, parameters, risk settings, cost model, dataset ID and a **data checksum**.

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

* **Results:** net P/L, return %, trade count, wins/losses/breakeven, win rate, average win and loss, largest win and loss.
* **Edge:** expectancy (money and R), profit factor (empty when there are no losses), average R:R.
* **Risk:** max drawdown (amount and %), longest win and loss streaks (breakeven trades break a streak), total costs, average holding time.
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

* **CSV import**: MT5 export format or generic OHLC, with a UTC offset for server-time exports. Bad rows are dropped and reported.
* **MT5 download** from a connected account.
* **Synthetic**: deterministic per seed, labelled SYNTHETIC everywhere.

Every dataset gets validation: gaps (ignoring weekends), duplicates, bad OHLC and spikes.

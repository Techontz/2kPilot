# Backtesting

> Status: **design, for Phase 6.**

## Goal

Find out honestly whether a strategy has an edge **after costs**, and make overfitting visible. A beautiful equity curve is not the goal.

## Flow

Select strategy version → instrument(s) → timeframe(s) → date range → starting capital → risk profile → cost model (spread, commission, slippage, swap) → run.

## Simulation rules (realism)

* **Same code path as live** for the strategy and the risk engine. Only the market-data source and the execution simulator differ.
* **Bar-close decisions:** signals use closed bars only. Fills happen at the *next* bar's open plus spread and slippage. There's no look-ahead.
* **Intra-bar ambiguity:** if a bar touches both the stop and the target, assume the **stop** was hit first (conservative), unless lower-timeframe data resolves it.
* **Costs:** spread (historical per-bar spread when available, otherwise a configured value), commission per lot, slippage model, and swap for positions held overnight.
* **Sizing:** the same position-sizing function as live, rounded to the broker volume step.

## Results

Starting and ending balance, net P/L, total return, trade count, wins and losses, win rate, average win and loss, **expectancy**, **profit factor**, **max drawdown**, R-multiple distribution, longest winning and losing streaks, equity curve, monthly returns, performance by instrument and by session, and the full trade list. Every figure shows "gross" and "after costs".

## Validation

| Technique | Purpose |
|---|---|
| In-sample / out-of-sample split | Tune on one period, judge on an unseen one |
| Walk-forward | Rolling optimise→test windows. Reports the stitched out-of-sample result |
| Parameter sensitivity | Heat-map around chosen params. A sharp peak signals overfitting |
| Regime breakdown | Results in trending, ranging and high/low-volatility periods |
| Cost stress | Re-run with 1.5× and 2× spread and slippage |

The UI shows in-sample and out-of-sample side by side, and **flags large degradation**. Every results screen states that historical performance doesn't guarantee future results.

## Reproducibility

A backtest record stores the strategy version, parameters, a data-set checksum, the cost model, the random seeds and the code version. Re-running it must reproduce identical results.

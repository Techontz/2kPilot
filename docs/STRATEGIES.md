# Strategies

## Contract (`strategy_engine/base.py`)

A strategy is a **pure decision function** over CLOSED candles:

```python
class Strategy(ABC):
    key, name, code_version, description
    Params: type[BaseModel]                          # validated, JSON-schema → UI form
    def timeframes(params) -> (entry_tf, *context_tfs)
    def required_bars(params) -> {Timeframe: count}
    def evaluate(view: MarketView, params) -> Evaluation
```

`Evaluation` = outcome (`SIGNAL` / `NO_SETUP` / `INSUFFICIENT_DATA`) + summary + a list of `Check(name, passed, detail)` + an optional `SignalIntent` (side, entry reference price, **mandatory stop loss**, take profit, reasons).

Strategies **never** place orders, size positions in money, or import a broker adapter. The risk engine sizes and decides; the execution engine sends.

* **Live:** the runner fetches closed candles from the broker (`StaticView`) when a new entry-timeframe bar closes, and stores every evaluation in `strategy_evaluations`, so you can see why a bar did *not* signal.
* **Backtest:** `CursorView` reveals only bars closed at the simulated time. Higher timeframes are resampled and appear only after their period ends.
* **Determinism:** strategies use fixed look-back windows, so live and backtest compute identical indicator values from the same bars.

## Trend Pullback V1 (`trend_pullback.py`)

A research starting point. **It is not claimed to be profitable.**

| Stage | Rule (defaults) | Parameters |
|---|---|---|
| Trend (H4) | Close vs EMA200; EMA50 vs EMA200; slope of EMA200 over 10 bars; optional swing structure | `higher_timeframe`, `ema_fast`, `ema_slow`, `require_fast_above_slow`, `require_slope`, `slope_lookback`, `use_structure` |
| Pullback (H1) | Within the last 6 bars, price came within 0.5 ATR of EMA50 | `entry_timeframe`, `pullback_lookback`, `pullback_zone_atr` |
| Not too deep | Deepest move beyond EMA50 ≤ 2.5 ATR | `max_pullback_atr` |
| Don't chase | Close ≤ 1.5 ATR from EMA50 | `max_extension_atr` |
| Confirmation | Close beyond the previous bar's high/low (or trend close / engulfing) | `confirmation` |
| Stop | Beyond the swing of the last 10 bars + 0.2 ATR (or N×ATR) | `stop_mode`, `swing_lookback`, `stop_buffer_atr`, `stop_atr_mult` |
| Target | 2R (or N×ATR) | `take_profit_mode`, `reward_risk`, `tp_atr_mult` |
| Direction | Long and/or short | `allow_long`, `allow_short` |

The risk engine then adds its own gates, including session filters, spread, minimum reward/risk and stop distance.

## Versions and assignments

* `strategy_versions` are **immutable**. Every signal, trade and backtest records its exact version.
* A new version is created from the UI form (generated from the parameter schema); invalid values are refused.
* An **assignment** = version × account × symbol. It is created **PAUSED** and must be enabled deliberately (the account needs a risk profile). Switching version pauses it again.
* Duplicate-signal protection: at most one signal per assignment, bar and side (unique constraint).

## Adding a strategy

1. Implement `Strategy` in `strategy_engine/<name>.py` with a Pydantic `Params` model (every threshold a field with a description).
2. Register it in `strategy_engine/registry.py`. It's seeded into the catalogue on startup.
3. Add tests: crafted candle series for each outcome, parameter validation, and look-ahead safety with `CursorView`.

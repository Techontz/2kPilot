# Strategies

> Status: **design, for Phase 4.** No strategy code exists yet.

## The contract

A strategy is a pure decision function. It reads market data and its own parameters, and outputs **signals (intentions)**. It never places orders, sizes positions in money terms, or knows which broker is used.

```python
class Strategy(Protocol):
    id: str                      # "trend_pullback"
    name: str
    version: str                 # semantic version; every param/code change = new StrategyVersion
    timeframes: tuple[Timeframe, ...]
    parameters_schema: type[BaseModel]   # Pydantic model → validation + UI form + backtest grid

    def required_history(self) -> dict[Timeframe, int]: ...
    def on_bar(self, ctx: StrategyContext) -> list[Signal]: ...
```

A `Signal` contains the strategy id and version, symbol, side, entry type, proposed entry, **mandatory stop-loss (invalidation) price**, take-profit, the reasons (which conditions passed), and the timestamps. The risk engine turns an approved signal into a position size, and the execution engine turns it into an order.

Pipeline: `market data → strategy → Signal → risk engine → execution engine → broker adapter`.

Strategies have `enabled = false` by default, and each one is assigned per account. **Creating a strategy never makes it trade.**

## Trend Pullback V1 (first research strategy)

A research starting point. **It isn't claimed to be profitable.** Every rule below is a parameter, and every parameter is backtestable.

| Stage | Default idea | Parameters |
|---|---|---|
| Trend (4H) | Close above/below EMA(slow). EMA(fast) above/below EMA(slow). Optional market-structure check (higher highs/lows) | `htf=H4`, `ema_fast=50`, `ema_slow=200`, `use_structure` |
| Pullback (1H) | Price retraces into a zone (e.g. between EMA(fast) and EMA(slow), or an ATR band) | `ltf=H1`, `pullback_zone`, `max_pullback_atr` |
| No chasing | Skip if price is more than N×ATR from the trend EMA | `max_extension_atr` |
| Confirmation | e.g. a close back in the trend direction, or a break of the pullback swing | `confirmation` |
| Stop (invalidation) | Beyond the pullback swing ± buffer, or N×ATR | `stop_mode`, `stop_buffer_atr` |
| Take profit | Fixed R multiple or structure-based | `rr_target=2.0`, `tp_mode` |
| Sessions | Allowed trading sessions (e.g. London/NY) | `sessions` |
| News | Optional blackout window (needs a calendar source) | `news_blackout_min` |

## Versioning

`strategy_versions` rows are immutable. Every signal, trade and backtest references the exact version, so results stay reproducible.

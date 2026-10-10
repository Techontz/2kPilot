# Strategies

> **Educational software, not advice.** Every template and every strategy you build here is a research starting point. None is claimed to be profitable. Past results — in backtests or on demo accounts — do not predict future results. Try everything with a backtest and on a demo account first.

**Strategies propose; the risk engine decides.** A strategy only says "BUY" or "SELL" (with a stop and a target) on a closed candle. Whether anything is traded — and how big — is decided by the risk engine ([RISK_ENGINE.md](RISK_ENGINE.md)): your STOP switch, mode, risk profile, daily loss limits, stake limits, sessions, spread and the broker's own rules all still apply.

Users create strategies **without programming**, in three ways:

| | Method | What happens |
|---|---|---|
| A | **Templates** | Six built-in rule sets (below). Activate one directly, or copy it and change it. |
| B | **Visual rule builder** | Dropdowns and number fields: WHEN conditions → THEN a buy/sell → EXIT rules. |
| C | **Describe it in plain English** | Claude drafts builder rules from your description; you review and edit them before saving. Nothing is saved automatically. |

All three produce the same thing: a **rule set** run by the `rules` strategy. Advanced, code-based strategies (Trend Pullback V1) remain available as built-ins.

## The rule-set format (`schema_version: 1`)

A rule set is **data, never code** — a fixed list of price fields, numbers, catalogued indicators and operators. Nothing in it is executed or evaluated as an expression. It is validated (Pydantic, `trading-engine/src/fxrobot/strategy_engine/rules/model.py`) every time it is saved, imported, drafted or run.

```json
{
  "schema_version": 1,
  "timeframe": "M5",
  "entry": {
    "buy":  {"all": [
      {"left": {"indicator": "ema", "params": {"period": 20}}, "op": "crosses_above",
       "right": {"indicator": "ema", "params": {"period": 50}}},
      {"left": {"indicator": "rsi", "params": {"period": 14}}, "op": "lt", "right": {"value": 70}}
    ]},
    "sell": {"any": [
      {"left": {"price": "close"}, "op": "crosses_below",
       "right": {"indicator": "lowest", "params": {"period": 20, "source": "low"}}}
    ]}
  },
  "filters": [
    {"left": {"price": "close"}, "op": "gt", "right": {"indicator": "sma", "params": {"period": 200}}}
  ],
  "exit": {
    "stop":   {"type": "atr", "atr_period": 14, "multiple": 2.0},
    "target": {"type": "rr", "ratio": 2.0},
    "close_buy_when":  {"any": [
      {"left": {"indicator": "rsi", "params": {"period": 14}}, "op": "gt", "right": {"value": 75}}
    ]},
    "close_sell_when": null
  }
}
```

Its plain-English summary (`to_text()`, stored with every version as `rules_text`):

> Buy when EMA 20 crosses above EMA 50 and RSI 14 is below 70. Sell when the close crosses below the lowest low of the previous 20 bars. Only trade when the close is above SMA 200. Close a buy early when RSI 14 is above 75. Stop: 2 × ATR 14 from the entry; target: 2 × the stop distance (Spot and Multiplier trades). Checked on every closed M5 bar.

| Part | Meaning |
|---|---|
| `timeframe` | `M1` `M5` `M15` `M30` `H1` `H4` `D1`. Rules are checked when a bar of this timeframe closes. |
| `entry.buy` / `entry.sell` | A group: `{"all": [...]}` (every condition) or `{"any": [...]}` (at least one). One level only — no nesting. At least one of buy/sell. |
| `filters` | Conditions that must **all** hold before any entry (e.g. a trend filter). |
| `exit.stop` | `{"type": "atr", "atr_period", "multiple"}` or `{"type": "pips", "pips"}`. Default 2 × ATR 14. |
| `exit.target` | `{"type": "rr", "ratio"}` (multiple of the stop distance), `atr`, `pips`, or `null`. Default 2R. Without a target, Spot trades are refused when the risk profile requires a minimum reward/risk. |
| `exit.close_buy_when` / `close_sell_when` | Optional early exits (groups like entries). |

**Operands** — exactly one of: `{"price": "open|high|low|close"}`, `{"value": 30}`, or `{"indicator": KEY, "params": {...}, "output": ...}` (omitted params/outputs take the catalogue defaults).

**Conditions** — `{"left", "op", "right"}` or, for `between`, `{"left", "op": "between", "low", "high"}` (inclusive). `crosses_above` / `crosses_below` take an optional `"within_bars": N` (1–50): the cross happened on this bar or up to N−1 bars ago.

* **Cross semantics:** "A crosses above B" = A ≤ B on the previous bar **and** A > B on this bar. Touching is not crossing. While either side is still warming up (no value yet on this or the previous bar) the condition is "not enough data yet".
* **Scales:** only operands on the same scale can be compared — prices with prices (and price-based indicators), RSI with numbers, MACD values with MACD values, %B with numbers, ATR with ATR. "RSI 14 crosses above EMA 50" is refused.

**Contracts.** The same rules drive every contract family (the assignment's contract decides):

| Contract | BUY / SELL | Stop / target | Exit conditions |
|---|---|---|---|
| Rise/Fall (Deriv) | CALL / PUT | Not used — the contract settles at expiry; the stake is the most it can lose | **Not used** — Rise/Fall always runs to expiry |
| Multiplier (Deriv) | MULTUP / MULTDOWN | Converted to money amounts, unless the assignment sets its own | Close (sell) the contract early |
| Spot (Paper) | long / short | The stop is mandatory; target optional | Close the position early |

**Limits & validation.** At most **12 conditions** in total; periods 1–500; Bollinger deviation 0.1–5; numbers within ±1,000,000,000; `within_bars` 1–50; MACD fast < slow; no comparing something with itself; no condition made only of numbers; a number can't be the left side of a cross; exit rules need the matching entry side; unknown keys are refused. Every problem comes back in plain English, one per line, e.g. `Buy rule, condition 1: MACD fast period (26) must be smaller than the slow period (12)`.

**Warm-up & determinism.** A rule set needs `warmup_bars()` closed bars (its longest look-back — ~3× the period for EMA, RSI, ATR and MACD, which are recursive — plus room to detect crosses). Live trading and backtests evaluate the **same fixed trailing window**, so they compute identical indicator values from the same bars.

**Explanations.** Every closed bar stores each condition's result with values, e.g. `EMA 20 (1.23450) crossed above EMA 50 (1.23400) ✓` or `RSI 14 is 41.2 — needs to be below 30 ✗` (Strategies → assignment → *Why no trade?*). Outcomes: `SIGNAL`, `NO_SETUP` (with the reason: no rule matched, a filter failed, or buy and sell matched at once — conflicting rules never trade), `INSUFFICIENT_DATA`.

## The catalogue (`GET /api/strategies/catalog`)

Served by the engine (`strategy_engine/rules/catalog.py` — the single source of truth for the builder **and** the drafting prompt) and cached by Laravel for 5 minutes.

| Indicator | Params (default) | Outputs | Notes |
|---|---|---|---|
| `sma` | period (50), source (close) | value | Simple average |
| `ema` | period (20), source (close) | value | Exponential average, seeded with the SMA |
| `rsi` | period (14) | value (0–100) | Wilder |
| `macd` | fast (12), slow (26), signal (9) | line, signal, histogram | |
| `bollinger` | period (20), stddev (2) | upper, middle, lower, percent_b | Population standard deviation; %B 0 = lower band, 1 = upper |
| `atr` | period (14) | value | Wilder; volatility, not direction |
| `highest` / `lowest` | period (20), source (high / low) | value | Of the **previous** N bars, current bar excluded (Donchian) — so "close crosses above highest high" is a breakout |
| `roc` | period (10) | value (%) | Rate of change |

Operators: `crosses_above` "crosses above", `crosses_below` "crosses below", `gt` "is above", `gte` "is at or above", `lt` "is below", `lte` "is at or below", `between` "is between". The catalogue also lists price fields, groups (`all`/`any`), stop and target types, limits, per-contract notes and `ai_drafting_available`.

## Templates

Built-ins are shared rows (`user_id` NULL, `source: template`, stable `slug`) seeded by the migration `2026_10_05_000510_seed_strategy_templates.php` from `backend/database/data/strategy_templates.json` (idempotent by slug; a changed template gets a new version). The engine's tests validate every template and check its `rules_text`. Users can activate a template directly or **copy** it to change it; templates themselves are read-only.

All suggest Deriv synthetic indices (`R_75`, `R_100`, `1HZ100V`) or forex majors on Paper, and a Rise/Fall contract lasting a few candles. Each carries the educational disclaimer.

| Template | Level | TF | Rules | When it struggles |
|---|---|---|---|---|
| **EMA crossover** (`ema-crossover`) | beginner | M5, Rise/Fall 25m | Buy when EMA 9 crosses above EMA 21; sell on the opposite cross. Stop 2 × ATR, target 1.5R. | Choppy, sideways markets (many small losing crosses); signals come late. |
| **RSI mean reversion** (`rsi-mean-reversion`) | beginner | M5, 25m | Buy when RSI 14 crosses back above 30; sell when it crosses back below 70. Spot/Multiplier close early when RSI passes 55 / 45. | Strong trends: RSI can stay oversold/overbought while price keeps going. |
| **Moving-average trend filter** (`ma-trend-filter`) | intermediate | M5, 25m | Buys only above SMA 200, sells only below it; enter when the close crosses back over EMA 20 after a pullback. Target 2R. | Reversals and flat markets: the SMA 200 is slow to turn. |
| **Bollinger Bands reversion** (`bollinger-reversion`) | intermediate | M5, 25m | Buy when the close crosses back above the lower band (20, 2); sell when it crosses back below the upper band. Close early at the middle band. | Breakouts and trends: price can "walk the band". |
| **MACD momentum confirmation** (`macd-momentum`) | intermediate | M5, 25m | MACD line crosses its signal line, histogram on the same side of 0, and the close on the same side of EMA 50. Target 2R. | Choppy markets; late entries. |
| **Breakout** (`breakout`) | intermediate | M15, Rise/Fall 1h | Buy when the close crosses above the highest high of the previous 20 bars; sell below the lowest low. Target 2R. | False breakouts that fall straight back into the range. |

Each template's `details` hold `how_it_works` (2–4 sentences), `struggles`, `suggested_timeframe`, `suggested_symbols`, `suggested_contract`, `difficulty` and `disclaimer`. **Trend Pullback V1** (`trend_pullback`, "advanced") stays a code strategy registered by the engine — see the bottom of this page.

## Method B — the visual builder (semantics)

* WHEN: pick a left operand (price / number / indicator + settings + output), an operator, and the right operand (or low & high for "is between"). Group conditions with **All** or **Any**.
* THEN: a buy rule, a sell rule, or both. If both match on the same bar, nothing is traded.
* FILTERS: optional conditions required before any entry.
* EXIT: stop and target (Spot/Multiplier), optional early-exit rules per side.
* Saving calls `POST /api/strategies` (`source: builder`); Laravel asks the engine to validate (`/internal/strategies/rules/validate`) and returns the engine's `problems` when it refuses. Every change after that is a new immutable version.

## Method C — describe it in plain English

`POST /api/strategies/draft {description, symbol?, timeframe?, contract_family?}` → Laravel → engine `POST /internal/strategies/draft` → Claude (`services/strategy_drafts.py`).

* **Model & call:** the official Anthropic Python SDK, model `ANTHROPIC_MODEL` (default `claude-opus-5-5`), adaptive thinking, effort `medium`, `max_tokens` 16000, **structured outputs** (a strict JSON schema for the draft envelope `{rules, explanation, warnings, unsupported}`; the rule set is flattened for the schema, converted, then **re-validated by the real validator**), server-side refusal fallback (`fallbacks: "default"`), 60-second timeout, 2 SDK retries.
* **Prompt:** a stable system prompt containing the catalogue; the user's description goes in the user message between `<strategy_description>` tags and is declared untrusted data, never instructions. Claude must use only the catalogue, prefer simple rules, never claim profitability, and list what the platform cannot do (news/sentiment, machine learning, martingale or stake increases after losses, guaranteed wins, several symbols, code) in `unsupported` — building the closest safe version, or `rules: null`.
* **Outcomes:** a draft (never saved — the user reviews it in the builder and saves it with `source: ai`); `ai_refused` (422); `ai_incomplete` (502, cut off); `ai_invalid_draft` (422, after **one** repair round in which the validator's messages are sent back); `ai_rate_limited` (503); `ai_unavailable` (502); `ai_not_configured` (503 — "Plain-English drafting isn't set up on this server").
* **What is sent to Anthropic:** the description, the optional symbol / timeframe / contract family, and the rule catalogue. No user id, account, balance, trade or broker data. Anthropic's data-handling terms apply to that text — don't put personal information in a description.
* **Setup:** set `ANTHROPIC_API_KEY` in `trading-engine/.env` ([SETUP.md](SETUP.md)). Without it the feature is off (`ai_drafting_available: false` in the catalogue).
* **Limits:** 10 drafts per user per hour (`AI_DRAFTS_PER_HOUR`); description 10–2000 characters; audit action `strategy.ai_draft` stores the description's **length** and the outcome, not the text.

## Import / export

`GET /api/strategies/{id}/export` downloads (rule-based strategies, including templates):

```json
{"format": "tradepilot.strategy", "schema_version": 1, "name": "My EMA cross", "description": "…", "rules": { …rule set… }}
```

`POST /api/strategies/import` accepts the same JSON (≤ 128 KB, rules ≤ 64 KB, name unique for you), validates the rules through the engine and creates a strategy with `source: import`. This is also the manual fallback for Method C: a rule set written elsewhere can be imported and reviewed.

## Versions, ownership and assignments

* Built-in strategies (`user_id` NULL) are shared and read-only for users (admins can add versions). Copy one (`POST /api/strategies/{id}/copy`, `source: copy`, `copied_from_id`) to get your own.
* `strategy_versions` are **immutable**; every signal, trade and backtest records its exact version. Rule-based versions store the rule set in `parameters` and its summary in `rules_text`.
* `DELETE /api/strategies/{id}`: refused while an assignment is enabled; **archived** (hidden, name freed, history kept) when trades, signals or backtests point at it; otherwise deleted.
* An **assignment** = version × one of your accounts × symbol × contract. `POST /api/strategies/{id}/activate {account_id, symbol, contract?}` creates or updates it with the **latest** version, checks the contract with the broker, and enables it (the account needs a risk profile). It still reports `blockers` — your STOP switch, mode, account switch, platform halt, engine offline — in `status_reason`. `POST /api/strategies/{id}/deactivate {account_id}` pauses them.
* Exit rules in live trading: after each evaluation the runner checks the assignment's open Spot/Multiplier trades and closes those whose exit rule holds (`exit_reason: STRATEGY`). In backtests they close at the next bar's open ([BACKTESTING.md](BACKTESTING.md)).
* Results on the Strategies page are **your own**: demo performance from PAPER/DEMO accounts only, LIVE kept separate, and your latest completed backtest.

## The strategy contract (code strategies)

A strategy is a **pure decision function** over CLOSED candles (`strategy_engine/base.py`):

```python
class Strategy(ABC):
    key, name, code_version, description
    Params: type[BaseModel]                          # validated, JSON-schema
    def timeframes(params) -> (entry_tf, *context_tfs)
    def required_bars(params) -> {Timeframe: count}
    def evaluate(view: MarketView, params) -> Evaluation
    def has_exit_rules(params) -> bool               # optional (default False)
    def evaluate_exit(view, params, side) -> ExitDecision | None   # optional early exits
```

Strategies **never** place orders, size positions in money, or import a broker adapter. Live: the runner fetches closed candles (`StaticView`) when a bar closes and stores every evaluation. Backtest: `CursorView` reveals only bars closed at the simulated time.

### Trend Pullback V1 (`trend_pullback.py`, advanced)

Higher-timeframe trend (H4: close vs EMA200, EMA50 vs EMA200, slope, optional structure) → pullback to EMA50 on H1 (within 0.5 ATR, not deeper than 2.5 ATR) → not over-extended → confirmation bar → stop beyond the swing, target 2R. Every threshold is a parameter. It is a research starting point, not claimed to be profitable.

### Adding a code strategy

1. Implement `Strategy` in `strategy_engine/<name>.py` with a Pydantic `Params` model.
2. Register it in `strategy_engine/registry.py`; the engine adds a shared template (version 1 = defaults) on start-up.
3. Add tests: crafted candles for each outcome, parameter validation, look-ahead safety.

**Known limitation:** walk-forward and sensitivity grids vary top-level parameters only, so they don't apply to rule sets yet (vary a rule by saving a new version and backtesting each).

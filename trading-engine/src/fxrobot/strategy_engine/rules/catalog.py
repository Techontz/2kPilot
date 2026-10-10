"""What the rule builder offers: indicators, operators, price fields and limits.

This module is the single source of truth for the builder UI (served through
Laravel at GET /api/strategies/catalog) and for the plain-English drafting
prompt. Adding an indicator = a spec here + a computation in `series.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from fxrobot.domain.market import Timeframe

SCHEMA_VERSION = 1

MAX_CONDITIONS = 12
MIN_PERIOD = 1
MAX_PERIOD = 500
MAX_WITHIN_BARS = 50
MAX_CONSTANT = 1_000_000_000.0

PRICE_FIELDS: dict[str, str] = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
}

# What an operand's numbers mean. Only operands on the same scale (or a plain
# number) can be compared: "RSI 14 crosses above EMA 50" is meaningless.
Scale = Literal["price", "oscillator", "ratio", "macd", "price_distance", "percent"]

SCALE_LABELS: dict[str, str] = {
    "price": "a price",
    "oscillator": "a 0–100 oscillator",
    "ratio": "a band position (0 = lower band, 1 = upper band)",
    "macd": "a MACD value (difference of two averages, around 0)",
    "price_distance": "a price distance (volatility)",
    "percent": "a percentage change",
}


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    kind: Literal["integer", "number", "source"]
    default: int | float | str
    minimum: float | None = None
    maximum: float | None = None
    description: str = ""

    def as_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "type": self.kind,
            "default": self.default,
            "description": self.description,
        }
        if self.kind == "source":
            data["options"] = list(PRICE_FIELDS)
        else:
            data["min"], data["max"] = self.minimum, self.maximum
        return data


@dataclass(frozen=True)
class OutputSpec:
    key: str
    label: str
    scale: Scale


@dataclass(frozen=True)
class IndicatorSpec:
    key: str
    label: str
    short: str
    description: str
    params: tuple[ParamSpec, ...]
    outputs: tuple[OutputSpec, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def default_output(self) -> str:
        return self.outputs[0].key

    def output(self, key: str) -> OutputSpec | None:
        return next((o for o in self.outputs if o.key == key), None)

    def param(self, key: str) -> ParamSpec | None:
        return next((p for p in self.params if p.key == key), None)

    def defaults(self) -> dict[str, int | float | str]:
        return {p.key: p.default for p in self.params}

    def as_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "short": self.short,
            "description": self.description,
            "params": [p.as_json() for p in self.params],
            "outputs": [
                {"key": o.key, "label": o.label, "scale": o.scale, "meaning": SCALE_LABELS[o.scale]}
                for o in self.outputs
            ],
            "default_output": self.default_output,
            "notes": list(self.notes),
        }


def _period(default: int, what: str = "bars in the average") -> ParamSpec:
    return ParamSpec(
        "period", "Period", "integer", default, MIN_PERIOD, MAX_PERIOD, f"Number of {what}."
    )


def _source(default: str) -> ParamSpec:
    return ParamSpec("source", "Price", "source", default, description="Which price to use.")


INDICATORS: dict[str, IndicatorSpec] = {
    s.key: s
    for s in (
        IndicatorSpec(
            "sma",
            "Simple moving average (SMA)",
            "SMA",
            "The average price of the last N bars. Smooths out noise; price above a rising "
            "average is a common definition of an uptrend.",
            (_period(50), _source("close")),
            (OutputSpec("value", "Value", "price"),),
        ),
        IndicatorSpec(
            "ema",
            "Exponential moving average (EMA)",
            "EMA",
            "Like the SMA, but recent bars count more, so it reacts faster to new moves.",
            (_period(20), _source("close")),
            (OutputSpec("value", "Value", "price"),),
        ),
        IndicatorSpec(
            "rsi",
            "Relative Strength Index (RSI)",
            "RSI",
            "Momentum from 0 to 100 (Wilder). Readings below 30 are often called oversold, "
            "above 70 overbought — in strong trends it can stay there for a long time.",
            (_period(14, "bars measured"),),
            (OutputSpec("value", "Value", "oscillator"),),
        ),
        IndicatorSpec(
            "macd",
            "MACD",
            "MACD",
            "The difference between a fast and a slow EMA (the MACD line), a signal line "
            "(an EMA of the MACD line) and the histogram (line − signal). Used to judge "
            "momentum: the line crossing above the signal line suggests momentum is turning up.",
            (
                ParamSpec("fast", "Fast EMA", "integer", 12, MIN_PERIOD, MAX_PERIOD),
                ParamSpec("slow", "Slow EMA", "integer", 26, MIN_PERIOD, MAX_PERIOD),
                ParamSpec("signal", "Signal EMA", "integer", 9, MIN_PERIOD, MAX_PERIOD),
            ),
            (
                OutputSpec("line", "MACD line", "macd"),
                OutputSpec("signal", "Signal line", "macd"),
                OutputSpec("histogram", "Histogram", "macd"),
            ),
            ("The fast period must be smaller than the slow period.",),
        ),
        IndicatorSpec(
            "bollinger",
            "Bollinger Bands",
            "Bollinger",
            "A moving average (middle band) with bands N standard deviations above and below. "
            "%B shows where the close sits: 0 = on the lower band, 1 = on the upper band.",
            (
                _period(20),
                ParamSpec(
                    "stddev",
                    "Standard deviations",
                    "number",
                    2.0,
                    0.1,
                    5.0,
                    "Band distance from the middle, in standard deviations.",
                ),
            ),
            (
                OutputSpec("upper", "Upper band", "price"),
                OutputSpec("middle", "Middle band", "price"),
                OutputSpec("lower", "Lower band", "price"),
                OutputSpec("percent_b", "%B (position within the bands)", "ratio"),
            ),
        ),
        IndicatorSpec(
            "atr",
            "Average True Range (ATR)",
            "ATR",
            "How far price typically moves per bar (Wilder). A volatility measure, not a "
            "direction — mostly used to size stops and targets.",
            (_period(14, "bars measured"),),
            (OutputSpec("value", "Value", "price_distance"),),
        ),
        IndicatorSpec(
            "highest",
            "Highest of previous bars (Donchian high)",
            "Highest",
            "The highest price of the previous N bars, NOT counting the current bar — so "
            "'close crosses above the highest high of 20 bars' is a breakout.",
            (_period(20, "previous bars"), _source("high")),
            (OutputSpec("value", "Value", "price"),),
        ),
        IndicatorSpec(
            "lowest",
            "Lowest of previous bars (Donchian low)",
            "Lowest",
            "The lowest price of the previous N bars, NOT counting the current bar.",
            (_period(20, "previous bars"), _source("low")),
            (OutputSpec("value", "Value", "price"),),
        ),
        IndicatorSpec(
            "roc",
            "Rate of change (ROC)",
            "ROC",
            "How much the close changed over N bars, in percent. Above 0 = higher than N bars ago.",
            (_period(10, "bars back"),),
            (OutputSpec("value", "Value", "percent"),),
        ),
    )
}

OPERATORS: dict[str, dict[str, Any]] = {
    "crosses_above": {
        "label": "crosses above",
        "description": "Was at or below the other value on the previous bar and is above it "
        "on this bar. With 'within the last N bars' the cross may have happened up to N bars ago.",
        "operands": ["right"],
        "supports_within_bars": True,
    },
    "crosses_below": {
        "label": "crosses below",
        "description": "Was at or above the other value on the previous bar and is below it "
        "on this bar.",
        "operands": ["right"],
        "supports_within_bars": True,
    },
    "gt": {"label": "is above", "description": "Strictly greater.", "operands": ["right"]},
    "gte": {"label": "is at or above", "description": "Greater or equal.", "operands": ["right"]},
    "lt": {"label": "is below", "description": "Strictly smaller.", "operands": ["right"]},
    "lte": {"label": "is at or below", "description": "Smaller or equal.", "operands": ["right"]},
    "between": {
        "label": "is between",
        "description": "Within an inclusive range (low ≤ value ≤ high).",
        "operands": ["low", "high"],
    },
}


def lookback(indicator: str, params: dict[str, Any]) -> int:
    """Bars an indicator needs before its value is meaningful and stable.

    Recursive indicators (EMA, RSI, ATR) get ~3× their period so that live
    trading and backtests, which both use a fixed trailing window, compute
    the same numbers.
    """
    p = int(params.get("period", 0) or 0)
    if indicator in ("sma", "bollinger"):
        return p
    if indicator == "ema":
        return 3 * p
    if indicator in ("rsi", "atr"):
        return 3 * p + 1
    if indicator == "macd":
        return 3 * int(params["slow"]) + int(params["signal"])
    return p + 1  # highest, lowest, roc


def catalog_json(ai_drafting_available: bool | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "timeframes": [tf.value for tf in Timeframe],
        "price_fields": [{"key": k, "label": v} for k, v in PRICE_FIELDS.items()],
        "indicators": [s.as_json() for s in INDICATORS.values()],
        "operators": [{"key": k, **v} for k, v in OPERATORS.items()],
        "groups": [
            {"key": "all", "label": "All of these must be true"},
            {"key": "any", "label": "At least one of these must be true"},
        ],
        "stop_types": [
            {"key": "atr", "label": "ATR multiple", "fields": ["atr_period", "multiple"]},
            {"key": "pips", "label": "Fixed pips", "fields": ["pips"]},
        ],
        "target_types": [
            {"key": "rr", "label": "Reward/risk multiple of the stop", "fields": ["ratio"]},
            {"key": "atr", "label": "ATR multiple", "fields": ["atr_period", "multiple"]},
            {"key": "pips", "label": "Fixed pips", "fields": ["pips"]},
        ],
        "limits": {
            "max_conditions": MAX_CONDITIONS,
            "min_period": MIN_PERIOD,
            "max_period": MAX_PERIOD,
            "max_within_bars": MAX_WITHIN_BARS,
            "max_constant": MAX_CONSTANT,
        },
        "contract_notes": {
            "RISE_FALL": "Rise/Fall contracts always run to expiry: exit conditions, stops "
            "and targets do not apply. The stake is the most you can lose.",
            "MULTIPLIER": "Exit conditions close the contract early. Stops and targets become "
            "money amounts unless the assignment sets its own.",
            "SPOT": "Paper only. Every trade has the stop below; exit conditions can close "
            "it earlier.",
        },
    }
    if ai_drafting_available is not None:
        data["ai_drafting_available"] = ai_drafting_available
    return data

"""Operand values over a window of closed candles, and condition checks.

Everything is computed on the same fixed trailing window (see
RuleSet.warmup_bars), so live trading and backtests see identical numbers.
The last element of every series is the most recent CLOSED bar.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fxrobot.domain.market import Candle
from fxrobot.strategy_engine.indicators import (
    FloatArray,
    adx,
    atr,
    bollinger,
    ema,
    highest,
    lowest,
    macd,
    roc,
    rsi,
    sma,
)
from fxrobot.strategy_engine.rules.catalog import OPERATORS
from fxrobot.strategy_engine.rules.model import CROSSES, Condition, Group, Operand


class Frame:
    """OHLC arrays for a window of candles, with a per-operand cache."""

    def __init__(self, candles: Sequence[Candle]) -> None:
        self.n = len(candles)
        self.prices: dict[str, FloatArray] = {
            "open": np.array([float(c.open) for c in candles]),
            "high": np.array([float(c.high) for c in candles]),
            "low": np.array([float(c.low) for c in candles]),
            "close": np.array([float(c.close) for c in candles]),
        }
        self._cache: dict[str, FloatArray] = {}

    def atr(self, period: int) -> FloatArray:
        key = f"atr({period})"
        if key not in self._cache:
            p = self.prices
            self._cache[key] = atr(p["high"], p["low"], p["close"], period)
        return self._cache[key]

    def series(self, operand: Operand) -> FloatArray:
        key = operand.key
        if key not in self._cache:
            self._cache[key] = self._compute(operand)
        return self._cache[key]

    def _compute(self, o: Operand) -> FloatArray:
        if o.value is not None:
            return np.full(self.n, float(o.value))
        if o.price is not None:
            return self.prices[o.price]
        p = o.params
        close = self.prices["close"]
        src = self.prices[str(p.get("source", "close"))]
        period = int(p.get("period", 0) or 0)
        if o.indicator == "sma":
            return sma(src, period)
        if o.indicator == "ema":
            return ema(src, period)
        if o.indicator == "rsi":
            return rsi(close, period)
        if o.indicator == "atr":
            return self.atr(period)
        if o.indicator == "roc":
            return roc(close, period)
        if o.indicator == "highest":
            return highest(src, period)
        if o.indicator == "lowest":
            return lowest(src, period)
        if o.indicator == "adx":
            line, plus, minus = adx(self.prices["high"], self.prices["low"], close, period)
            return {"adx": line, "plus_di": plus, "minus_di": minus}[o.output or "adx"]
        if o.indicator == "macd":
            line, signal, hist = macd(close, int(p["fast"]), int(p["slow"]), int(p["signal"]))
            return {"line": line, "signal": signal, "histogram": hist}[o.output or "line"]
        if o.indicator == "bollinger":
            upper, middle, lower, pct_b = bollinger(close, period, float(p["stddev"]))
            outputs = {"upper": upper, "middle": middle, "lower": lower, "percent_b": pct_b}
            return outputs[o.output or "upper"]
        raise ValueError(f"unknown indicator {o.indicator!r}")  # the model forbids this


@dataclass(frozen=True)
class ConditionResult:
    text: str  # the rule, e.g. "EMA 20 crosses above EMA 50"
    passed: bool
    detail: str  # with values, e.g. "EMA 20 (1.2345) crossed above EMA 50 (1.2340) ✓"
    available: bool = True  # False while an indicator is still warming up


def _fmt(value: float, digits: int, operand: Operand) -> str:
    if operand.value is not None:
        return f"{value:g}"
    scale = operand.scale
    if scale in ("price", "price_distance", "macd"):
        return f"{value:.{digits}f}" if scale != "macd" else f"{value:.{digits + 1}f}"
    return f"{value:.2f}" if scale == "ratio" else f"{value:.1f}"


def _crossed(left: FloatArray, right: FloatArray, i: int, above: bool) -> bool:
    """A cross on bar i: on the other side (or equal) at i-1, strictly beyond at i."""
    a0, b0, a1, b1 = left[i - 1], right[i - 1], left[i], right[i]
    if np.isnan([a0, b0, a1, b1]).any():
        return False
    return bool(a0 <= b0 and a1 > b1) if above else bool(a0 >= b0 and a1 < b1)


def check(frame: Frame, cond: Condition, digits: int) -> ConditionResult:
    """Evaluate one condition on the last closed bar, with an explanation."""
    text = cond.to_text()
    left = frame.series(cond.left)
    lv = float(left[-1]) if frame.n else float("nan")
    others = [o for o in (cond.right, cond.low, cond.high) if o is not None]
    values = [float(frame.series(o)[-1]) if frame.n else float("nan") for o in others]
    if not frame.n or np.isnan([lv, *values]).any():
        return ConditionResult(text, False, f"{text}: not enough data yet ✗", available=False)

    def show(o: Operand, v: float) -> str:
        return o.label() if o.is_constant else f"{o.label()} ({_fmt(v, digits, o)})"

    lhs = show(cond.left, lv)
    if cond.op in CROSSES:
        assert cond.right is not None  # noqa: S101
        right = frame.series(cond.right)
        above = cond.op == "crosses_above"
        window = cond.within_bars or 1
        if frame.n < 2 or np.isnan([left[-2], right[-2]]).any():
            # A cross needs the previous bar too.
            return ConditionResult(text, False, f"{text}: not enough data yet ✗", available=False)
        hit = next(
            (
                ago
                for ago in range(window)
                if frame.n - 1 - ago >= 1 and _crossed(left, right, frame.n - 1 - ago, above)
            ),
            None,
        )
        verb = "crossed above" if above else "crossed below"
        rhs = show(cond.right, values[0])
        if hit is None:
            where = "on this bar" if window == 1 else f"in the last {window} bars"
            relation = "above" if lv > values[0] else "below" if lv < values[0] else "equal to"
            direction = "above" if above else "below"
            detail = f"{lhs} did not cross {direction} {rhs} {where} (now {relation}) ✗"
            return ConditionResult(text, False, detail)
        when = "" if hit == 0 else f" {hit} bar{'s' if hit > 1 else ''} ago"
        return ConditionResult(text, True, f"{lhs} {verb} {rhs}{when} ✓")
    if cond.op == "between":
        assert cond.low is not None and cond.high is not None  # noqa: S101
        lo, hi = values
        ok = lo <= lv <= hi
        detail = (
            f"{lhs} is between {show(cond.low, lo)} and {show(cond.high, hi)}"
            if ok
            else f"{lhs} — needs between {show(cond.low, lo)} and {show(cond.high, hi)}"
        )
        return ConditionResult(text, ok, detail + (" ✓" if ok else " ✗"))
    assert cond.right is not None  # noqa: S101
    rv = values[0]
    ok = {
        "gt": lv > rv,
        "gte": lv >= rv,
        "lt": lv < rv,
        "lte": lv <= rv,
    }[cond.op]
    label = str(OPERATORS[cond.op]["label"])
    rhs = show(cond.right, rv)
    if ok:
        return ConditionResult(text, True, f"{lhs} {label} {rhs} ✓")
    needs = label.removeprefix("is ")
    now = (
        cond.left.label()
        if cond.left.is_constant
        else f"{cond.left.label()} is {_fmt(lv, digits, cond.left)}"
    )
    return ConditionResult(text, False, f"{now} — needs to be {needs} {rhs} ✗")


def check_group(frame: Frame, group: Group, digits: int) -> tuple[bool, list[ConditionResult]]:
    """Evaluate every condition (for complete explanations), then combine."""
    results = [check(frame, c, digits) for c in group.conditions]
    passed = (
        all(r.passed for r in results) if group.mode == "all" else any(r.passed for r in results)
    )
    return passed, results

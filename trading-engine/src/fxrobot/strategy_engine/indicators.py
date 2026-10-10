"""Technical indicators on float arrays (numpy). Pure functions, no look-ahead:
the value at index i depends only on inputs at indices <= i."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def ema(values: FloatArray, period: int) -> FloatArray:
    """Exponential moving average seeded with the SMA of the first `period` values.

    Entries before the seed are NaN.
    """
    out = np.full(values.shape, np.nan)
    if period <= 0 or len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    out[period - 1] = values[:period].mean()
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def atr(high: FloatArray, low: FloatArray, close: FloatArray, period: int) -> FloatArray:
    """Wilder's Average True Range."""
    n = len(close)
    out = np.full(n, np.nan)
    if n <= period:
        return out
    prev_close = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    out[period] = tr[1 : period + 1].mean()
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def swing_points(
    high: FloatArray, low: FloatArray, left: int = 2, right: int = 2
) -> tuple[list[int], list[int]]:
    """Indices of confirmed swing highs/lows.

    A swing at i is only confirmed once `right` later bars exist, so the most
    recent `right` bars can never be swings — that lag is what keeps this free
    of look-ahead.
    """
    highs, lows = [], []
    for i in range(left, len(high) - right):
        window_h = high[i - left : i + right + 1]
        window_l = low[i - left : i + right + 1]
        if high[i] == window_h.max() and (window_h == high[i]).sum() == 1:
            highs.append(i)
        if low[i] == window_l.min() and (window_l == low[i]).sum() == 1:
            lows.append(i)
    return highs, lows


# ── indicators for the rule builder (strategy_engine/rules) ──────────────


def sma(values: FloatArray, period: int) -> FloatArray:
    """Simple moving average; NaN until `period` values exist."""
    out = np.full(values.shape, np.nan)
    if period <= 0 or len(values) < period:
        return out
    csum = np.cumsum(np.insert(values, 0, 0.0))
    out[period - 1 :] = (csum[period:] - csum[:-period]) / period
    return out


def rsi(values: FloatArray, period: int) -> FloatArray:
    """Wilder's RSI (0–100). The first value is at index `period`.

    No losses in the averaging window → 100; no movement at all → 50.
    """
    n = len(values)
    out = np.full(n, np.nan)
    if period <= 0 or n <= period:
        return out
    change = np.diff(values)
    gains, losses = np.clip(change, 0, None), np.clip(-change, 0, None)
    avg_gain, avg_loss = gains[:period].mean(), losses[:period].mean()

    def value(g: float, loss: float) -> float:
        if loss == 0:
            return 50.0 if g == 0 else 100.0
        return 100.0 - 100.0 / (1.0 + g / loss)

    out[period] = value(avg_gain, avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = value(avg_gain, avg_loss)
    return out


def macd(
    values: FloatArray, fast: int, slow: int, signal: int
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """(MACD line, signal line, histogram). The signal EMA starts once the line exists."""
    line = ema(values, fast) - ema(values, slow)
    sig = np.full(values.shape, np.nan)
    valid = np.flatnonzero(~np.isnan(line))
    if len(valid):
        start = int(valid[0])
        sig[start:] = ema(line[start:], signal)
    return line, sig, line - sig


def bollinger(
    values: FloatArray, period: int, stddev: float
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """(upper, middle, lower, %B) with the population standard deviation.

    %B = (close − lower) ÷ (upper − lower): 0 at the lower band, 1 at the upper.
    """
    n = len(values)
    middle = sma(values, period)
    sd = np.full(n, np.nan)
    if 0 < period <= n:
        windows = np.lib.stride_tricks.sliding_window_view(values, period)
        sd[period - 1 :] = windows.std(axis=1)
    upper, lower = middle + stddev * sd, middle - stddev * sd
    width = upper - lower
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_b = np.where(width > 0, (values - lower) / width, np.nan)
    return upper, middle, lower, pct_b


def highest(values: FloatArray, period: int) -> FloatArray:
    """Highest value of the PREVIOUS `period` bars (the current bar excluded).

    Excluding the current bar is what makes "close breaks the highest high"
    a breakout test instead of a comparison with itself.
    """
    out = np.full(values.shape, np.nan)
    if period <= 0 or len(values) <= period:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(values[:-1], period)
    out[period:] = windows.max(axis=1)
    return out


def lowest(values: FloatArray, period: int) -> FloatArray:
    """Lowest value of the PREVIOUS `period` bars (the current bar excluded)."""
    out = np.full(values.shape, np.nan)
    if period <= 0 or len(values) <= period:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(values[:-1], period)
    out[period:] = windows.min(axis=1)
    return out


def roc(values: FloatArray, period: int) -> FloatArray:
    """Rate of change in percent: (value ÷ value `period` bars ago − 1) × 100."""
    out = np.full(values.shape, np.nan)
    if period <= 0 or len(values) <= period:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        out[period:] = (values[period:] / values[:-period] - 1.0) * 100.0
    return out

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

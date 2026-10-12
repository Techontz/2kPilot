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


def adx(
    high: FloatArray, low: FloatArray, close: FloatArray, period: int
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Wilder's Average Directional Index: (ADX, +DI, −DI), each 0–100.

    +DM = today's high − yesterday's high when that beats yesterday's low − today's
    low (and is positive); −DM the mirror. TR, +DM and −DM are Wilder-smoothed
    (first value = the sum of the first `period` bars, then
    S[i] = S[i−1] − S[i−1]/period + x[i]); ±DI = 100 × smoothed DM ÷ smoothed TR;
    DX = 100 × |+DI − −DI| ÷ (+DI + −DI); ADX = the average of the first `period`
    DX values, then Wilder-smoothed. ±DI start at index `period`, ADX at
    2 × period − 1. Earlier entries are NaN. A bar range of zero gives DI 0
    (and DX 0 when both DIs are 0).
    """
    n = len(close)
    plus_di, minus_di, out = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    if period <= 0 or n <= period:
        return out, plus_di, minus_di
    up = np.diff(high)
    down = -np.diff(low)
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    prev_close = close[:-1]
    tr = np.maximum(
        high[1:] - low[1:], np.maximum(np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close))
    )
    # Index j of tr/plus_dm/minus_dm describes bar j + 1.
    s_tr, s_plus, s_minus = tr[:period].sum(), plus_dm[:period].sum(), minus_dm[:period].sum()
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if i > period:
            j = i - 1
            s_tr = s_tr - s_tr / period + tr[j]
            s_plus = s_plus - s_plus / period + plus_dm[j]
            s_minus = s_minus - s_minus / period + minus_dm[j]
        p_di = 100.0 * s_plus / s_tr if s_tr > 0 else 0.0
        m_di = 100.0 * s_minus / s_tr if s_tr > 0 else 0.0
        plus_di[i], minus_di[i] = p_di, m_di
        total = p_di + m_di
        dx[i] = 100.0 * abs(p_di - m_di) / total if total > 0 else 0.0
    first = 2 * period - 1
    if n > first:
        out[first] = dx[period : first + 1].mean()
        for i in range(first + 1, n):
            out[i] = (out[i - 1] * (period - 1) + dx[i]) / period
    return out, plus_di, minus_di


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

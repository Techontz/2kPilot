"""Market-regime classifier: transparent, deterministic rules over CLOSED candles.

Used by strategies (Adaptive Trend & Momentum trades only in a matching trend
regime), by the backtester (results by the regime at entry) and shown in the UI
through each evaluation's checks. Every threshold is configurable.

Rules, applied in this order to the last closed bar of the series:

1. UNCERTAIN        fewer than `required_bars()` closed bars (not enough information).
2. HIGH_VOLATILITY  the current ATR is at or above the `high_vol_percentile` of its
                    own last `atr_history` values (percentile rank, current included).
3. TREND_UP         ADX ≥ `trend_adx`, EMA fast > EMA slow, EMA fast rising over
                    `slope_bars` bars and +DI > −DI.
   TREND_DOWN       the mirror image.
4. SIDEWAYS         ADX < `sideways_adx`.
5. UNCERTAIN        anything else: ADX between the two thresholds, or a strong ADX
                    whose EMAs, slope and DIs disagree (conflicting indicators).

Every value is computed on the same fixed trailing window (`required_bars()`),
so live trading and backtests read identical numbers from the same bars.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

from fxrobot.domain.market import Candle
from fxrobot.strategy_engine.indicators import adx, atr, ema


class Regime(StrEnum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    UNCERTAIN = "UNCERTAIN"

    @property
    def is_trend(self) -> bool:
        return self in (Regime.TREND_UP, Regime.TREND_DOWN)


@dataclass(frozen=True)
class RegimeConfig:
    ema_fast: int = 20
    ema_slow: int = 50
    adx_period: int = 14
    atr_period: int = 14
    trend_adx: float = 25.0  # ADX at or above: strong enough to call a trend
    sideways_adx: float = 20.0  # ADX below: no trend (range-bound)
    slope_bars: int = 5  # bars over which the fast EMA must rise (fall)
    atr_history: int = 100  # bars of ATR history for the percentile
    high_vol_percentile: float = 90.0  # 100 = never HIGH_VOLATILITY

    def __post_init__(self) -> None:
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast must be smaller than ema_slow")
        if self.sideways_adx > self.trend_adx:
            raise ValueError("sideways_adx cannot exceed trend_adx")
        if min(self.ema_fast, self.adx_period, self.atr_period, self.slope_bars) < 1:
            raise ValueError("periods must be positive")
        if self.atr_history < 10:
            raise ValueError("atr_history must be at least 10 bars")
        if not 50.0 <= self.high_vol_percentile <= 100.0:
            raise ValueError("high_vol_percentile must be between 50 and 100")

    def required_bars(self) -> int:
        """The fixed trailing window: recursive indicators get ~3× their period."""
        return max(
            3 * self.ema_slow + self.slope_bars,
            6 * self.adx_period,
            self.atr_history + 3 * self.atr_period,
        )

    def as_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class RegimeReading:
    regime: Regime
    reason: str
    bars: int
    adx: float | None = None
    plus_di: float | None = None
    minus_di: float | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None
    slope: float | None = None
    atr: float | None = None
    atr_percentile: float | None = None

    def label(self) -> str:
        """e.g. "TREND_UP — ADX 31.2 ≥ 25, EMA20 above EMA50 and rising, +DI > −DI"."""
        return f"{self.regime.value} — {self.reason}"

    def as_json(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "reason": self.reason,
            "bars": self.bars,
            "adx": _round(self.adx),
            "plus_di": _round(self.plus_di),
            "minus_di": _round(self.minus_di),
            "atr_percentile": _round(self.atr_percentile),
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def percentile_rank(history: np.ndarray[Any, Any], value: float) -> float:
    """Share (0–100) of `history` values at or below `value` (NaNs ignored)."""
    clean = history[np.isfinite(history)]
    if clean.size == 0:
        return float("nan")
    return float((clean <= value).sum() / clean.size * 100.0)


def classify(candles: Sequence[Candle], cfg: RegimeConfig | None = None) -> RegimeReading:
    """The regime at the LAST bar of `candles` (all of which must be closed)."""
    cfg = cfg or RegimeConfig()
    need = cfg.required_bars()
    window = list(candles[-need:])
    if len(window) < need:
        return RegimeReading(
            Regime.UNCERTAIN,
            f"not enough history: {len(window)} of {need} closed bars",
            len(window),
        )
    close = np.array([float(c.close) for c in window])
    high = np.array([float(c.high) for c in window])
    low = np.array([float(c.low) for c in window])
    fast, slow = ema(close, cfg.ema_fast), ema(close, cfg.ema_slow)
    adx_line, plus, minus = adx(high, low, close, cfg.adx_period)
    atr_line = atr(high, low, close, cfg.atr_period)
    a, p_di, m_di = float(adx_line[-1]), float(plus[-1]), float(minus[-1])
    f, s = float(fast[-1]), float(slow[-1])
    slope = float(fast[-1] - fast[-1 - cfg.slope_bars])
    cur_atr = float(atr_line[-1])
    values = (a, p_di, m_di, f, s, slope, cur_atr)
    if not all(np.isfinite(v) for v in values):
        return RegimeReading(Regime.UNCERTAIN, "indicators not available yet", len(window))
    pct = percentile_rank(atr_line[-cfg.atr_history :], cur_atr)

    def reading(regime: Regime, reason: str) -> RegimeReading:
        return RegimeReading(regime, reason, len(window), a, p_di, m_di, f, s, slope, cur_atr, pct)

    ef, es = f"EMA{cfg.ema_fast}", f"EMA{cfg.ema_slow}"
    if cfg.high_vol_percentile < 100 and pct >= cfg.high_vol_percentile:
        return reading(
            Regime.HIGH_VOLATILITY,
            f"ATR at the {pct:.0f}th percentile of its last {cfg.atr_history} bars "
            f"(limit {cfg.high_vol_percentile:.0f})",
        )
    strong = a >= cfg.trend_adx
    up = f > s and slope > 0 and p_di > m_di
    down = f < s and slope < 0 and m_di > p_di
    if strong and up:
        return reading(
            Regime.TREND_UP,
            f"ADX {a:.1f} ≥ {cfg.trend_adx:g}, {ef} above {es} and rising, +DI {p_di:.1f} > "
            f"−DI {m_di:.1f}",
        )
    if strong and down:
        return reading(
            Regime.TREND_DOWN,
            f"ADX {a:.1f} ≥ {cfg.trend_adx:g}, {ef} below {es} and falling, −DI {m_di:.1f} > "
            f"+DI {p_di:.1f}",
        )
    if a < cfg.sideways_adx:
        return reading(Regime.SIDEWAYS, f"ADX {a:.1f} below {cfg.sideways_adx:g}: no trend")
    if strong:
        side = "above" if f > s else "below"
        return reading(
            Regime.UNCERTAIN,
            f"conflicting indicators: ADX {a:.1f} is strong but {ef} is {side} {es}, slope "
            f"{slope:+.4g}, +DI {p_di:.1f} / −DI {m_di:.1f}",
        )
    return reading(
        Regime.UNCERTAIN,
        f"ADX {a:.1f} between {cfg.sideways_adx:g} and {cfg.trend_adx:g}: trend not clear",
    )

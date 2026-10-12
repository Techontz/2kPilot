"""Adaptive Trend & Momentum — multi-timeframe trend, momentum and volatility filters.

Idea (every threshold is a parameter):
1. Trend timeframe (default M15) must be in a TREND regime (strategy_engine/regime):
   ADX ≥ min_adx, EMA fast above (below) EMA slow and sloping, +DI/−DI agreeing,
   ATR not at an extreme of its own history. SIDEWAYS, HIGH_VOLATILITY and
   UNCERTAIN mean NO_TRADE, with the regime as the reason.
2. Entry timeframe (default M5): price pulled back to within an ATR-scaled band of
   EMA fast over the last closed bars, without breaking too deep.
3. RSI shows RENEWED momentum (it dipped below a level and turned back up through
   it, or — in "rising" mode — rose over the last bar inside sane bounds). A
   threshold alone is never enough: the turn must happen.
4. The last CLOSED candle confirms: bullish (bearish) and closing above the prior
   close or above EMA fast (below for sells).
5. Entry-timeframe ATR within bounds (a flat or exploding feed is not traded).
6. Stop = entry ∓ stop_atr_mult × ATR, target = reward_risk × the stop distance.
   The risk engine still decides everything else (sizing, limits, switches).

Closed candles only. The trend timeframe is only used up to the last bar that
had fully CLOSED when the entry bar closed (bars are filtered by
open + timeframe ≤ decision time, the same rule as the backtester's CursorView),
and every value is computed on a fixed trailing window so a truncated history
gives exactly the same decision as the full one.

Contracts: needs a real stop and target, so Spot (Paper) or Multiplier (Deriv,
where the stop and target become `limit_order` money amounts). Rise/Fall has no
stop or target and settles at expiry: refused.

This is a research starting point. It is not claimed to be profitable.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fxrobot.domain.contracts import ContractFamily
from fxrobot.domain.market import Candle, Side, Timeframe
from fxrobot.strategy_engine.base import (
    Check,
    Evaluation,
    MarketView,
    Outcome,
    SignalIntent,
    Strategy,
)
from fxrobot.strategy_engine.indicators import atr, ema, rsi
from fxrobot.strategy_engine.regime import Regime, RegimeConfig, RegimeReading, classify


class AdaptiveTrendMomentumParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trend_timeframe: Timeframe = Field(
        Timeframe.M15, description="Timeframe that defines the trend."
    )
    entry_timeframe: Timeframe = Field(Timeframe.M5, description="Timeframe used for entries.")
    ema_fast: int = Field(20, ge=5, le=200, description="Fast EMA period (both timeframes).")
    ema_slow: int = Field(50, ge=10, le=400, description="Slow EMA period (trend timeframe).")
    rsi_period: int = Field(14, ge=2, le=100, description="RSI period (entry timeframe).")
    adx_period: int = Field(14, ge=2, le=100, description="ADX period (trend timeframe).")
    atr_period: int = Field(14, ge=2, le=100, description="ATR period (both timeframes).")
    min_adx: float = Field(
        25.0, ge=5, le=80, description="Minimum trend-timeframe ADX for a trend."
    )
    sideways_adx: float = Field(
        20.0, ge=1, le=80, description="ADX below this = SIDEWAYS regime (no trade)."
    )
    trend_slope_bars: int = Field(
        5, ge=1, le=50, description="Bars over which the trend EMA fast must rise (fall)."
    )
    atr_history_bars: int = Field(
        100, ge=20, le=500, description="Trend-timeframe ATR history for the volatility percentile."
    )
    high_vol_percentile: float = Field(
        90.0, ge=50, le=100, description="ATR percentile that means HIGH_VOLATILITY (100 = off)."
    )
    pullback_lookback: int = Field(
        6,
        ge=1,
        le=50,
        description="Closed entry bars (before the signal bar) searched for a pullback.",
    )
    pullback_atr_band: float = Field(
        0.5, ge=0, le=5, description="How close (in ATR) price must come to the entry EMA fast."
    )
    max_pullback_atr: float = Field(
        2.0, ge=0.1, le=10, description="Deepest allowed move beyond the entry EMA fast (ATR)."
    )
    rsi_mode: Literal["cross", "rising"] = Field(
        "cross",
        description="cross: RSI dipped below rsi_level and turned back up through it (mirror "
        "for sells); rising: RSI rose (fell) over the last closed bar.",
    )
    rsi_level: float = Field(50.0, ge=20, le=80, description="Momentum level RSI must regain.")
    rsi_lookback: int = Field(
        6,
        ge=1,
        le=50,
        description="Bars in which RSI must have been on the other side of the level.",
    )
    rsi_upper: float = Field(70.0, ge=50, le=95, description="No buys at or above this RSI.")
    rsi_lower: float = Field(30.0, ge=5, le=50, description="No sells at or below this RSI.")
    min_atr_pct: float = Field(
        0.005,
        ge=0,
        le=5,
        description="Minimum entry ATR as % of price (a flat feed is not traded).",
    )
    max_atr_pct: float = Field(
        1.0, gt=0, le=20, description="Maximum entry ATR as % of price (extreme volatility)."
    )
    stop_atr_mult: float = Field(1.5, ge=0.2, le=10, description="Stop distance in entry ATR.")
    reward_risk: float = Field(
        2.0, ge=0.5, le=10, description="Target = reward_risk × stop distance."
    )
    # Strategy-level risk caps: they can only tighten the account's risk profile.
    risk_per_trade_pct: float = Field(
        0.5,
        ge=0.01,
        le=5,
        description="Cap on risk per trade (% of balance; tightens the profile).",
    )
    max_daily_loss_pct: float = Field(
        2.0, gt=0, le=100, description="Cap on the daily loss limit (%; tightens the profile)."
    )
    max_open_positions: int = Field(
        1, ge=1, le=50, description="Cap on open positions on the account (tightens the profile)."
    )
    allow_long: bool = True
    allow_short: bool = True

    @model_validator(mode="after")
    def _check(self) -> AdaptiveTrendMomentumParams:
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast must be smaller than ema_slow")
        if self.trend_timeframe.seconds <= self.entry_timeframe.seconds:
            raise ValueError("trend_timeframe must be above entry_timeframe")
        if self.trend_timeframe.seconds % self.entry_timeframe.seconds:
            raise ValueError("trend_timeframe must be a whole multiple of entry_timeframe")
        if self.sideways_adx > self.min_adx:
            raise ValueError("sideways_adx cannot exceed min_adx")
        if not self.rsi_lower < self.rsi_level < self.rsi_upper:
            raise ValueError("rsi_lower < rsi_level < rsi_upper is required")
        if self.min_atr_pct >= self.max_atr_pct:
            raise ValueError("min_atr_pct must be below max_atr_pct")
        if not (self.allow_long or self.allow_short):
            raise ValueError("allow at least one direction")
        return self

    def regime_config(self) -> RegimeConfig:
        return RegimeConfig(
            ema_fast=self.ema_fast,
            ema_slow=self.ema_slow,
            adx_period=self.adx_period,
            atr_period=self.atr_period,
            trend_adx=self.min_adx,
            sideways_adx=self.sideways_adx,
            slope_bars=self.trend_slope_bars,
            atr_history=self.atr_history_bars,
            high_vol_percentile=self.high_vol_percentile,
        )

    def htf_window(self) -> int:
        return self.regime_config().required_bars()

    def ltf_window(self) -> int:
        return max(
            3 * self.ema_fast,
            3 * self.rsi_period + self.rsi_lookback + 2,
            3 * self.atr_period + 1,
            self.pullback_lookback + 5,
        )


def closed_before(candles: list[Candle], timeframe: Timeframe, moment: Any) -> list[Candle]:
    """Only bars that had fully closed at `moment` (open + timeframe ≤ moment)."""
    return [c for c in candles if c.time + timeframe.delta <= moment]


class AdaptiveTrendMomentum(Strategy):
    key: ClassVar[str] = "adaptive_trend_momentum"
    name: ClassVar[str] = "Adaptive Trend & Momentum"
    code_version: ClassVar[str] = "1.0.0"
    description: ClassVar[str] = (
        "Uses trend, momentum, and volatility filters to identify potential trading "
        "opportunities while controlling risk."
    )
    Params = AdaptiveTrendMomentumParams
    contract_families: ClassVar[tuple[ContractFamily, ...] | None] = (
        ContractFamily.SPOT,
        ContractFamily.MULTIPLIER,
    )
    contract_reasons: ClassVar[dict[ContractFamily, str]] = {
        ContractFamily.RISE_FALL: (
            "Adaptive Trend & Momentum needs a stop loss and a take profit; Rise/Fall "
            "contracts have neither and settle at expiry. Choose Multiplier on Deriv "
            "(or Spot on Paper)."
        ),
    }
    symbols: ClassVar[tuple[str, ...] | None] = ("R_10", "R_25")

    def timeframes(self, params: Any) -> tuple[Timeframe, ...]:
        p: AdaptiveTrendMomentumParams = params
        return (p.entry_timeframe, p.trend_timeframe)

    def required_bars(self, params: Any) -> dict[Timeframe, int]:
        p: AdaptiveTrendMomentumParams = params
        return {p.entry_timeframe: p.ltf_window(), p.trend_timeframe: p.htf_window()}

    def risk_caps(self, params: Any) -> dict[str, Any]:
        p: AdaptiveTrendMomentumParams = params
        return {
            "risk_per_trade_pct": Decimal(str(p.risk_per_trade_pct)),
            "max_daily_loss_pct": Decimal(str(p.max_daily_loss_pct)),
            "max_open_positions": p.max_open_positions,
        }

    def regime(self, view: MarketView, params: Any) -> RegimeReading:
        p: AdaptiveTrendMomentumParams = params
        ltf = view.candles(p.entry_timeframe)
        htf = list(view.candles(p.trend_timeframe)[-(p.htf_window() + 2) :])
        if ltf:
            htf = closed_before(htf, p.trend_timeframe, ltf[-1].time + p.entry_timeframe.delta)
        return classify(htf, p.regime_config())

    def evaluate(self, view: MarketView, params: Any) -> Evaluation:
        p: AdaptiveTrendMomentumParams = params
        etf, ttf = p.entry_timeframe, p.trend_timeframe
        ltf = list(view.candles(etf)[-p.ltf_window() :])
        bar_time = ltf[-1].time if ltf else None
        decision_time = ltf[-1].time + etf.delta if ltf else None
        # Only the tail is needed; a forming bar (if a view ever hands one over) is
        # among the last two, so two extra bars keep the window full after filtering.
        htf_all = list(view.candles(ttf)[-(p.htf_window() + 2) :])
        htf = (
            closed_before(htf_all, ttf, decision_time) if decision_time is not None else htf_all
        )[-p.htf_window() :]
        if len(ltf) < p.ltf_window() or len(htf) < p.htf_window():
            return Evaluation(
                Outcome.INSUFFICIENT_DATA,
                f"No trade: need {p.ltf_window()} {etf} and {p.htf_window()} {ttf} closed bars "
                f"(have {len(ltf)} / {len(htf)}).",
                bar_time,
                [
                    Check(
                        "Enough closed candles",
                        False,
                        f"{len(ltf)} of {p.ltf_window()} {etf}, "
                        f"{len(htf)} of {p.htf_window()} {ttf}",
                    )
                ],
            )
        assert decision_time is not None  # noqa: S101 — ltf is not empty here
        digits = view.symbol.digits

        def fmt(value: float) -> str:
            return f"{value:.{digits}f}"

        checks: list[Check] = []

        def no_trade(outcome: Outcome = Outcome.NO_SETUP) -> Evaluation:
            failed = next(c for c in checks if not c.passed)
            return Evaluation(
                outcome,
                f"No trade: {failed.name.lower()} — {failed.detail}"[:300],
                bar_time,
                checks,
            )

        # 0. Fresh trend data: the last closed trend bar must be the one that closed
        #    at or just before the decision time (a gap or a stale feed is not traded).
        expected = ttf.floor(decision_time) - ttf.delta
        fresh = htf[-1].time >= expected
        checks.append(
            Check(
                "Data fresh",
                fresh,
                f"last closed {ttf} bar {htf[-1].time:%Y-%m-%d %H:%M} UTC"
                + ("" if fresh else f", expected {expected:%Y-%m-%d %H:%M} UTC (stale or gap)"),
            )
        )
        if not fresh:
            return no_trade(Outcome.INSUFFICIENT_DATA)

        # 1–2. Trend regime on the trend timeframe.
        reading = classify(htf, p.regime_config())
        checks.append(Check("Market regime", reading.regime.is_trend, reading.label()))
        if (
            reading.adx is not None
            and reading.ema_fast is not None
            and reading.ema_slow is not None
        ):
            checks.append(
                Check(
                    f"{ttf} trend strength",
                    reading.adx >= p.min_adx,
                    f"ADX {reading.adx:.1f} (min {p.min_adx:g})",
                )
            )
            checks.append(
                Check(
                    f"{ttf} EMA{p.ema_fast} vs EMA{p.ema_slow}",
                    reading.ema_fast != reading.ema_slow,
                    f"EMA{p.ema_fast} {fmt(reading.ema_fast)} "
                    f"{'>' if reading.ema_fast > reading.ema_slow else '<'} "
                    f"EMA{p.ema_slow} {fmt(reading.ema_slow)}",
                )
            )
        if not reading.regime.is_trend:
            outcome = (
                Outcome.INSUFFICIENT_DATA
                if reading.regime is Regime.UNCERTAIN and reading.adx is None
                else Outcome.NO_SETUP
            )
            return Evaluation(
                outcome, f"No trade: regime {reading.label()}"[:300], bar_time, checks
            )
        side = Side.BUY if reading.regime is Regime.TREND_UP else Side.SELL
        allowed = p.allow_long if side is Side.BUY else p.allow_short
        checks.append(
            Check(
                "Direction allowed",
                allowed,
                f"{side.value}s are {'allowed' if allowed else 'switched off in the parameters'}",
            )
        )
        if not allowed:
            return no_trade()
        s = side.sign

        # Entry timeframe values.
        close = np.array([float(c.close) for c in ltf])
        open_ = np.array([float(c.open) for c in ltf])
        high = np.array([float(c.high) for c in ltf])
        low = np.array([float(c.low) for c in ltf])
        fast = ema(close, p.ema_fast)
        r = rsi(close, p.rsi_period)
        a = atr(high, low, close, p.atr_period)
        cur_atr, cur_fast = float(a[-1]), float(fast[-1])
        if not (np.isfinite(cur_atr) and np.isfinite(cur_fast) and np.isfinite(r[-2])):
            checks.append(Check("Indicators ready", False, f"{etf} ATR/EMA/RSI not available yet"))
            return no_trade(Outcome.INSUFFICIENT_DATA)

        # 6. Volatility / execution conditions on the entry timeframe.
        atr_pct = cur_atr / close[-1] * 100 if close[-1] > 0 else 0.0
        vol_ok = p.min_atr_pct <= atr_pct <= p.max_atr_pct
        checks.append(
            Check(
                "Volatility",
                vol_ok,
                f"{etf} ATR {fmt(cur_atr)} = {atr_pct:.4f}% of price "
                f"(allowed {p.min_atr_pct:g}–{p.max_atr_pct:g}%)",
            )
        )

        # 3. Pullback toward EMA fast within the ATR band, over recent closed bars.
        window = slice(-1 - p.pullback_lookback, -1)
        band = p.pullback_atr_band * cur_atr
        if side is Side.BUY:
            touched = bool((low[window] <= fast[window] + band).any())
            depth = float((fast[window] - low[window]).max()) / cur_atr
        else:
            touched = bool((high[window] >= fast[window] - band).any())
            depth = float((high[window] - fast[window]).max()) / cur_atr
        checks.append(
            Check(
                "Pullback to EMA",
                touched,
                f"price came within {p.pullback_atr_band:g} ATR of EMA{p.ema_fast} in the last "
                f"{p.pullback_lookback} bars"
                if touched
                else f"no pullback to within {p.pullback_atr_band:g} ATR of EMA{p.ema_fast} in "
                f"the last {p.pullback_lookback} bars",
            )
        )
        checks.append(
            Check(
                "Pullback not too deep",
                depth <= p.max_pullback_atr,
                f"deepest move beyond EMA{p.ema_fast}: {max(depth, 0):.2f} ATR "
                f"(max {p.max_pullback_atr:g})",
            )
        )

        # 4. Renewed momentum — never a threshold alone.
        now_rsi, prev_rsi = float(r[-1]), float(r[-2])
        recent = r[-1 - p.rsi_lookback : -1]
        if p.rsi_mode == "cross":
            if side is Side.BUY:
                momentum = (
                    bool((recent < p.rsi_level).any())
                    and now_rsi >= p.rsi_level
                    and now_rsi > prev_rsi
                )
                how = f"dipped below {p.rsi_level:g} and turned up through it"
            else:
                momentum = (
                    bool((recent > p.rsi_level).any())
                    and now_rsi <= p.rsi_level
                    and now_rsi < prev_rsi
                )
                how = f"rose above {p.rsi_level:g} and turned down through it"
        else:
            momentum = (now_rsi - prev_rsi) * s > 0
            how = "rose over the last closed bar" if s > 0 else "fell over the last closed bar"
        sane = now_rsi < p.rsi_upper if s > 0 else now_rsi > p.rsi_lower
        bound = f"below {p.rsi_upper:g}" if s > 0 else f"above {p.rsi_lower:g}"
        checks.append(
            Check(
                "RSI momentum",
                momentum,
                f"RSI {p.rsi_period} {prev_rsi:.1f} → {now_rsi:.1f}: "
                + (how if momentum else f"has not {how}"),
            )
        )
        checks.append(Check("RSI not extreme", sane, f"RSI {now_rsi:.1f} must be {bound}"))

        # 5. Confirmation by the last CLOSED candle.
        body = (close[-1] - open_[-1]) * s > 0
        beyond = (close[-1] - close[-2]) * s > 0 or (close[-1] - cur_fast) * s > 0
        word = "bullish" if s > 0 else "bearish"
        checks.append(
            Check(
                "Confirmation candle",
                body and beyond,
                f"{word} close {fmt(close[-1])} "
                + (
                    f"{'above' if s > 0 else 'below'} the prior close {fmt(close[-2])} "
                    f"or EMA{p.ema_fast} {fmt(cur_fast)}"
                    if body and beyond
                    else f"not confirmed (open {fmt(open_[-1])}, prior close {fmt(close[-2])}, "
                    f"EMA{p.ema_fast} {fmt(cur_fast)})"
                ),
            )
        )
        if not all(c.passed for c in checks):
            return no_trade()

        # Stop and target.
        entry = float(close[-1])
        risk = p.stop_atr_mult * cur_atr
        stop = entry - s * risk
        target = entry + s * p.reward_risk * risk
        quant = Decimal(1).scaleb(-digits)

        def dec(value: float) -> Decimal:
            return Decimal(repr(float(value))).quantize(quant, rounding=ROUND_HALF_UP)

        if stop <= 0 or dec(stop) == dec(entry):
            checks.append(Check("Valid stop", False, "the ATR stop is too small for the price"))
            return no_trade()
        checks.append(
            Check(
                "Stop & target",
                True,
                f"stop {fmt(stop)} ({p.stop_atr_mult:g} ATR), target {fmt(target)} "
                f"({p.reward_risk:g}:1)",
            )
        )
        signal = SignalIntent(
            side=side,
            timeframe=etf,
            bar_time=ltf[-1].time,
            entry_price=dec(entry),
            stop_loss=dec(stop),
            take_profit=dec(target),
            reasons=[c.detail for c in checks if c.passed],
        )
        return Evaluation(
            Outcome.SIGNAL,
            f"{side.value} signal: {reading.regime.value} on {ttf}, pullback to EMA{p.ema_fast}, "
            "RSI momentum renewed, confirmed by the closed candle.",
            bar_time,
            checks,
            signal,
        )
